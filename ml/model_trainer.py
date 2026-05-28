from datetime import datetime

import numpy as np

import optuna
from ml.model_registry import ModelRegistry
from ml.preprocessing import FeaturePreprocessor
from utils.logger import get_logger
from utils.time_utils import IST


class ModelTrainer:
    def __init__(
        self,
        max_depth=6,
        learning_rate=0.05,
        n_estimators=300,
        subsample=0.9,
        colsample_bytree=0.9,
        validation_fraction=0.2,
    ):
        self.params = {
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "n_estimators": n_estimators,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
        }
        self.validation_fraction = validation_fraction
        self.preprocessor = FeaturePreprocessor()
        self.registry = ModelRegistry()
        self.logger = get_logger(self.__class__.__name__)
        self.min_promote_roc_auc = 0.52
        self.min_promote_f1 = 0.05

    def train(self, days=30, start_date=None, end_date=None, promote_if_better=True, optuna_trials=0):
        raw = self.preprocessor.load_feature_store(
            start_date=start_date,
            end_date=end_date,
            days=days if start_date is None else None,
            require_labels=True,
        )
        x, y, metadata, artifact = self.preprocessor.prepare_training_data(raw)
        self._validate_training_data(x, y)

        split_index = max(1, int(len(x) * (1 - self.validation_fraction)))
        if split_index >= len(x):
            split_index = len(x) - 1

        x_train, x_valid = x.iloc[:split_index], x.iloc[split_index:]
        y_train, y_valid = y.iloc[:split_index], y.iloc[split_index:]
        self._validate_training_data(x_train, y_train)
        self._validate_training_data(x_valid, y_valid, validation=True)

        num_positive = int(y_train.sum())
        num_negative = len(y_train) - num_positive
        scale_pos_weight = float(num_negative / num_positive) if num_positive > 0 else 1.0

        if optuna_trials and optuna_trials > 0:
            best_params = self._run_optuna(x_train, y_train, x_valid, y_valid, optuna_trials)
            self.params.update(best_params)
        else:
            best_params = {}

        model = self._build_model(scale_pos_weight=scale_pos_weight)
        model.fit(x_train, y_train, verbose=True)
        metrics = self._evaluate(model, x_valid, y_valid)
        metrics.update(
            {
                "rows_total": int(len(x)),
                "rows_train": int(len(x_train)),
                "rows_validation": int(len(x_valid)),
                "positive_rate": float(y.mean()),
            }
        )

        version = self._new_version()
        train_start = metadata["time"].min() if not metadata.empty else None
        train_end = metadata["time"].max() if not metadata.empty else None
        artifact["hyperparameters"] = {**self.params}
        artifact["decision_threshold"] = float(metrics.get("optimal_threshold", 0.5))
        self.registry.save_model(
            model=model,
            version=version,
            metrics=metrics,
            artifact=artifact,
            model_type="xgboost",
            train_start=train_start,
            train_end=train_end,
        )

        if promote_if_better and self._should_promote(metrics):
            self.registry.promote_model(version)

        self.logger.info("Trained model %s metrics=%s", version, metrics)
        return version, metrics

    def evaluate_latest(self, days=1, start_date=None, end_date=None):
        bundle = self.registry.loadlatestmodel()
        raw = self.preprocessor.load_feature_store(
            start_date=start_date,
            end_date=end_date,
            days=days if start_date is None else None,
            require_labels=True,
        )
        x, y, _, _ = self.preprocessor.prepare_training_data(raw)
        if x.empty:
            raise ValueError("No evaluation data found")
        x = self._align_to_artifact(x, bundle["artifact"])
        metrics = self._evaluate(bundle["model"], x, y)
        self.registry.record_metrics(bundle["version"], **metrics)
        return bundle["version"], metrics

    def _build_model(self, scale_pos_weight=1.0, extra_params=None):
        try:
            from xgboost import XGBClassifier
        except Exception as exc:
            raise RuntimeError(
                "xgboost is not installed. Run: python3 -m pip install -r requirements.txt"
            ) from exc

        params = {**self.params, **(extra_params or {})}
        return XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=1,
            verbosity=1,
            scale_pos_weight=scale_pos_weight,
            **params,
        )

    def _evaluate(self, model, x_valid, y_valid):
        try:
            from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
        except Exception as exc:
            raise RuntimeError(
                "scikit-learn is not installed. Run: python3 -m pip install -r requirements.txt"
            ) from exc

        probabilities = model.predict_proba(x_valid)[:, 1]
        
        best_f1 = -1.0
        best_threshold = 0.5
        
        # Test thresholds from 0.05 to 0.95 to find the optimal decision boundary
        for thresh in np.arange(0.05, 0.96, 0.05):
            preds = (probabilities >= thresh).astype(int)
            f = float(f1_score(y_valid, preds, zero_division=0))
            if f > best_f1:
                best_f1 = f
                best_threshold = float(thresh)
                
        # If the model is completely blind and all F1s are 0, default to 0.5
        if best_f1 <= 0:
            best_threshold = 0.5
            
        predictions = (probabilities >= best_threshold).astype(int)
        
        metrics = {
            "accuracy": float(accuracy_score(y_valid, predictions)),
            "precision": float(precision_score(y_valid, predictions, zero_division=0)),
            "recall": float(recall_score(y_valid, predictions, zero_division=0)),
            "f1": float(f1_score(y_valid, predictions, zero_division=0)),
            "optimal_threshold": float(best_threshold),
        }
        if len(set(y_valid)) > 1:
            metrics["roc_auc"] = float(roc_auc_score(y_valid, probabilities))
        else:
            metrics["roc_auc"] = None
        return metrics

    def _run_optuna(self, x_train, y_train, x_valid, y_valid, trials=50):
        from sklearn.metrics import f1_score

        scale_pos_weight = float((len(y_train) - y_train.sum()) / (y_train.sum() or 1.0))

        def objective(trial):
            params = {
                "max_depth": trial.suggest_int("max_depth", 3, 12),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "subsample": trial.suggest_float("subsample", 0.5, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
            }
            model = self._build_model(scale_pos_weight=scale_pos_weight, extra_params=params)
            model.fit(x_train, y_train, verbose=False)
            metrics = self._evaluate(model, x_valid, y_valid)
            return float(metrics.get("f1", 0.0))

        sampler = optuna.samplers.TPESampler(seed=42)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=trials)

        self.logger.info(
            "Optuna completed %s trials and selected params=%s best_f1=%.4f",
            trials,
            study.best_params,
            study.best_value,
        )
        return study.best_params

    def _validate_training_data(self, x, y, validation=False):
        if len(x) < 2:
            raise ValueError("Not enough labeled feature rows to train/evaluate")
        if not validation and len(set(y)) < 2:
            raise ValueError(
                "Training data has only one label class. Collect more data or adjust label thresholds."
            )

    def _align_to_artifact(self, x, artifact):
        columns = artifact["feature_columns"]
        fill_values = artifact.get("fill_values", {})
        for column in columns:
            if column not in x:
                x[column] = fill_values.get(column, 0.0)
        return x[columns].fillna(fill_values).fillna(0.0).astype(float)

    def _should_promote(self, metrics):
        current_roc_auc = metrics.get("roc_auc")
        current_f1 = metrics.get("f1", 0)
        if current_roc_auc is not None and float(current_roc_auc) < self.min_promote_roc_auc:
            self.logger.warning(
                "Model will not be promoted: roc_auc %.4f is below %.4f",
                current_roc_auc,
                self.min_promote_roc_auc,
            )
            return False
        if float(current_f1 or 0) < self.min_promote_f1:
            self.logger.warning(
                "Model will not be promoted: f1 %.4f is below %.4f",
                current_f1 or 0,
                self.min_promote_f1,
            )
            return False

        best = self.registry.getbestmodel()
        if not best:
            return True

        current_score = current_roc_auc
        if current_score is None:
            current_score = metrics.get("f1", 0)

        best_metrics = best.get("metrics") or {}
        best_score = best_metrics.get("roc_auc")
        if best_score is None:
            best_score = best_metrics.get("f1", 0)

        return float(current_score or 0) >= float(best_score or 0)

    def _new_version(self):
        return "model_" + datetime.now(IST).strftime("%Y%m%d_%H%M%S")

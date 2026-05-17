import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from ml.model_registry import loadlatestmodel

def main():
    print("Loading the latest AI model from the registry...")
    try:
        bundle = loadlatestmodel()
    except Exception as e:
        print(f"Failed to load model: {e}")
        return

    model = bundle.get("model")
    artifact = bundle.get("artifact", {})
    feature_names = artifact.get("feature_columns", [])

    if not model or not feature_names:
        print("Model or feature columns not found in the bundle.")
        return

    try:
        importances = model.feature_importances_
    except AttributeError:
        print("Model does not support feature importances.")
        return

    feature_importances = list(zip(feature_names, importances))
    feature_importances.sort(key=lambda x: x[1], reverse=True)

    print(f"\n--- AI Feature Importance Analysis (Model: {bundle.get('version')}) ---")
    print(f"{'Feature Name':<35} | {'Importance':<10}")
    print("-" * 50)
    
    for name, imp in feature_importances:
        if imp == 0.0:
            print(f"\033[91m{name:<35} | {imp:.5f}\033[0m") # Red for useless
        elif imp < 0.005:
            print(f"\033[93m{name:<35} | {imp:.5f}\033[0m") # Yellow for low impact
        else:
            print(f"\033[92m{name:<35} | {imp:.5f}\033[0m") # Green for high impact

    useless = [name for name, imp in feature_importances if imp == 0.0]
    low_impact = [name for name, imp in feature_importances if 0.0 < imp < 0.005]

    print("\n--- Summary ---")
    print(f"Total Features Analyzed: {len(feature_names)}")
    print(f"Highly Predictive Features: {len(feature_names) - len(useless) - len(low_impact)}")
    print(f"Low Impact Features (<0.005): {len(low_impact)}")
    print(f"Completely Useless Features (0.0): {len(useless)}")
    
    if useless:
        print("\nFeatures you should consider removing:")
        for u in useless:
            print(f"  - {u}")

if __name__ == "__main__":
    main()

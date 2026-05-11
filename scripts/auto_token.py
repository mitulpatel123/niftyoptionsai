import os
import sys
import pyotp
from dhanhq import DhanLogin
from pathlib import Path

def generate_and_save_dhan_token():
    env_file = Path(__file__).resolve().parents[1] / ".env"
    
    # Simple manual dotenv load to ensure we have the vars if running directly
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    if k not in os.environ:
                        os.environ[k] = v

    client_id = os.environ.get("DHAN_CLIENT_ID")
    pin = os.environ.get("DHAN_PIN")
    totp_secret = os.environ.get("DHAN_TOTP_SECRET")

    if not client_id or not pin or not totp_secret:
        print("[ERROR] Missing DHAN_CLIENT_ID, DHAN_PIN, or DHAN_TOTP_SECRET in environment variables.")
        return False
    
    print("--- Automatically Generating Dhan Access Token ---")
    try:
        login = DhanLogin(client_id)
        totp = pyotp.TOTP(totp_secret).now()
        
        response = login.generate_token(pin=pin, totp=totp)
        access_token = response.get('accessToken')
        
        if access_token:
            print(f"Successfully generated new token. Expiry: {response.get('expiryTime')}")
            
            # Read existing .env file
            if env_file.exists():
                with open(env_file, 'r') as f:
                    lines = f.readlines()
            else:
                lines = []
            
            # Update or append DHAN_ACCESS_TOKEN
            token_updated = False
            for i, line in enumerate(lines):
                if line.startswith("DHAN_ACCESS_TOKEN="):
                    lines[i] = f"DHAN_ACCESS_TOKEN={access_token}\n"
                    token_updated = True
                    break
            
            if not token_updated:
                lines.append(f"DHAN_ACCESS_TOKEN={access_token}\n")
            
            # Write back to .env
            with open(env_file, 'w') as f:
                f.writelines(lines)
            
            print(f"Updated {env_file} with new access token.")
            # Set the environment variable for the current process
            os.environ['DHAN_ACCESS_TOKEN'] = access_token
            return True
        else:
            print(f"Failed to extract access token from response: {response}")
            return False
            
    except Exception as e:
        print(f"Error generating token: {e}")
        return False

if __name__ == "__main__":
    generate_and_save_dhan_token()

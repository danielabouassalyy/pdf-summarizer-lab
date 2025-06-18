import os
import requests

# Read your env-vars
endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
key      = os.environ["AZURE_OPENAI_KEY"]

# List deployments via REST
url = f"{endpoint}/openai/deployments?api-version=2023-05-15"

resp = requests.get(
    url,
    headers={
        "api-key": key,
        "Content-Type": "application/json"
    }
)
print("Status:", resp.status_code)
print(resp.json())

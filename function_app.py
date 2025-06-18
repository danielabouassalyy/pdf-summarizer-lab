import logging
import os
import json
from datetime import datetime

import azure.functions as func
import azure.durable_functions as df
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
import requests

# Durable Functions app
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Blob client
blob_svc = BlobServiceClient.from_connection_string(os.environ["BLOB_STORAGE_ENDPOINT"])

# 1️⃣ Blob trigger
@app.blob_trigger(arg_name="myblob", path="input", connection="BLOB_STORAGE_ENDPOINT")
@app.durable_client_input(client_name="client")
async def blob_trigger(myblob: func.InputStream, client):
    logging.info(f"Trigger blob {myblob.name} ({myblob.length} bytes)")
    name = myblob.name.split("/")[-1]
    await client.start_new("orchestrator", client_input=name)

# 2️⃣ Orchestrator
@app.orchestration_trigger(context_name="context")
def orchestrator(context):
    blob_name = context.get_input()
    opts = df.RetryOptions(first_retry_interval_in_milliseconds=5000, max_number_of_attempts=3)

    text    = yield context.call_activity_with_retry("analyze_pdf", opts, blob_name)
    summary = yield context.call_activity_with_retry("summarize_text", opts, text)
    outblob = yield context.call_activity_with_retry("write_summary", opts, {"blob": blob_name, "summary": summary})
    return outblob

# 3️⃣ PDF → text
@app.activity_trigger(input_name="blobName")
def analyze_pdf(blobName):
    logging.info("analyze_pdf")
    blob = blob_svc.get_container_client("input").get_blob_client(blobName)
    pdf_bytes = blob.download_blob().readall()

    recog = DocumentAnalysisClient(
        os.environ["COGNITIVE_SERVICES_ENDPOINT"],
        AzureKeyCredential(os.environ["COGNITIVE_SERVICES_KEY"])
    )
    poller = recog.begin_analyze_document("prebuilt-layout", document=pdf_bytes, locale="en-US")
    pages = poller.result().pages

    txt = "\n".join(
        line.content
        for p in pages
        for line in p.lines
    )
    return txt

# 4️⃣ Text → summary via REST
@app.activity_trigger(input_name="text")
def summarize_text(text: str):
    logging.info("summarize_text via REST")
    endpoint   = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
    api_ver    = "2025-01-01-preview"

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
    headers = {
        "api-key": os.environ["AZURE_OPENAI_KEY"],
        "Content-Type": "application/json"
    }
    body = {
        "messages": [{"role": "user", "content": text}],
        "max_tokens": 200
    }

    resp = requests.post(url, headers=headers, json=body)
    resp.raise_for_status()
    choice = resp.json()["choices"][0]["message"]["content"]
    return choice

# 5️⃣ Write summary back
@app.activity_trigger(input_name="input")
def write_summary(input: dict):
    blob_name = input["blob"]
    summary   = input["summary"]
    ts        = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    out_name  = f"{blob_name}-{ts}.txt"

    blob_svc.get_container_client("output")\
        .upload_blob(name=out_name, data=summary)
    return out_name

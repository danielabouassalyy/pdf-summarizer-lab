# Azure PDF Summarizer Lab

**An intelligent PDF summarizer using Azure Durable Functions, Form Recognizer & OpenAI.**

## Overview

This project ingests PDFs from an Azure Blob Storage “input” container, extracts text via Form Recognizer, generates a summary via Azure OpenAI (GPT-3.5), and writes the result to an “output” container. It’s implemented as a Durable Functions orchestration:

1. **Blob Trigger** – kicks off when a PDF lands in `input/`
2. **Analyze PDF** – reads and OCRs the PDF (Form Recognizer)
3. **Summarize Text** – calls Azure OpenAI to generate a summary
4. **Write Summary** – drops a `.txt` summary into `output/`

##  Repo Structure
.
├── function_app.py # Durable Functions orchestration & activities
├── host.json # Functions host configuration
├── requirements.txt # Python dependencies
├── local.settings.json # excluded – my local secrets
├── .gitignore # ignores venv, local.settings.json, azurite data
└── README.md



## Prerequisites

- Python 3.9+  
- Azure Functions Core Tools v4  
- Azure Storage Emulator or Azurite (for local dev)
- An Azure Blob Storage account  
- An Azure Form Recognizer resource  
- An Azure OpenAI resource with a deployed “gpt35turbo” model  

## Azure Resource Setup

### 1. Storage Account

1. **Create Storage Account**  
   - In the Azure Portal, click **Create a resource** → **Storage** → **Storage account**.  
   - Fill in **Subscription**, **Resource group**, **Name** (e.g. `pdflabstore`), **Region**, **Performance** (Standard), **Replication** (LRS).  
   - Click **Review + create**, then **Create**.

2. **Create Blob Containers**  
   - Navigate to your new Storage Account → **Blob service** → **Containers**.  
   - Click **+ Container**, name it **input**, and set **Public access level** to **Private**.  
   - Repeat to create **output** (also Private).

3. **Grab Connection String**  
   - Go to **Access keys** under **Security + networking**.  
   - Copy one of the **Connection strings**—you’ll use this for both `AzureWebJobsStorage` and `BLOB_STORAGE_ENDPOINT`.

---

### 2. Form Recognizer (Cognitive Services)

1. **Create Form Recognizer**  
   - In the Portal, click **Create a resource** → **AI + Machine Learning** → **Form Recognizer**.  
   - Choose your **Resource group**, give it a **Name** (e.g. `pdflab-ocr`), select **Region**, and pick a **Pricing tier**.  
   - Click **Review + create**, then **Create**.

2. **Get Endpoint & Key**  
   - Once deployed, open your Form Recognizer resource.  
   - Under **Keys and Endpoint**, copy:  
     - **Endpoint** (e.g. `https://pdflab-ocr.cognitiveservices.azure.com/`)  
     - **Key** (one of the two keys)

---

### 3. Azure OpenAI

1. **Create Azure OpenAI Resource**  
   - Click **Create a resource** → **AI + Machine Learning** → **Azure OpenAI**.  
   - Fill in **Resource group**, **Name** (e.g. `pdflab-openai`), **Region**, **Pricing tier** (Standard S0).  
   - Click **Review + create**, then **Create**.

2. **Deploy the Model**  
   - After creation, open **Azure OpenAI Studio** from the resource blade.  
   - Go to **Deployments** → **+ New deployment**.  
     - **Model**: `gpt-35-turbo`  
     - **Deployment name**: `gpt35turbo` (avoid extra hyphens)  
   - Click **Deploy** and wait for provisioning to finish.

3. **Get Endpoint & Key**  
   - Back in the Azure Portal, on your Azure OpenAI resource:  
     - **Endpoint** (e.g. `https://pdflab-openai.openai.azure.com/`)  
     - Under **Keys and Endpoint**, copy **Key 1**

---

### 4. Configuration Reference

Once you have all of the above, your **local.settings.json** (and Azure Function App settings env) should look like:

| Setting                         | Value                                        |
|---------------------------------|----------------------------------------------|
| `AzureWebJobsStorage`           | `<your-storage-connection-string>`           |
| `BLOB_STORAGE_ENDPOINT`         | `<your-storage-connection-string>`           |
| `COGNITIVE_SERVICES_ENDPOINT`   | `https://pdflab-ocr.cognitiveservices.azure.com/` |
| `COGNITIVE_SERVICES_KEY`        | `<your-form-recognizer-key>`                 |
| `AZURE_OPENAI_ENDPOINT`         | `https://pdflab-openai.openai.azure.com/`    |
| `AZURE_OPENAI_KEY`              | `<your-azure-openai-key>`                    |
| `AZURE_OPENAI_DEPLOYMENT_NAME`  | `gpt35turbo`                                 |

now the Function App can read PDFs from **input/**, OCR them, summarize via GPT-3.5, and write the result to **output/**!


### 1. Clone & Install

```bash
git clone https://github.com/your-org/pdf-summarizer-lab.git
cd pdf-summarizer-lab
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```
### 2. Configure Local Settings
Create a file named local.settings.json in the repo root:
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage":    "<your-connection-string>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "BLOB_STORAGE_ENDPOINT":  "<same-connection-string>",
    "COGNITIVE_SERVICES_ENDPOINT": "https://<your-ocr>.cognitiveservices.azure.com/",
    "COGNITIVE_SERVICES_KEY":      "<your-ocr-key>",
    "AZURE_OPENAI_ENDPOINT":       "https://<your-openai>.openai.azure.com/",
    "AZURE_OPENAI_KEY":            "<your-openai-key>",
    "AZURE_OPENAI_DEPLOYMENT_NAME":"gpt35turbo"
  }
}
```
### 3. Run 
activate virtual env
```bash
venv\Scripts\activate
```

Fire up your Functions host in verbose mode so you can see each step:
```bash
func start --verbose
```
Test it

Upload a PDF into your input container (via Portal, Storage Explorer, or Az CLI).

Watch the console logs spin through analyze_pdf, summarize_text, write_summary.

Inspect the new .txt in your output container—it should contain your GPT summary!

## `function_app.py` Breakdown
### Imports & Setup

- Standard libs: logging, os, json, datetime

- Azure Functions + Durable: azure.functions, azure.durable_functions

- Blob storage client: BlobServiceClient

- Form Recognizer client: DocumentAnalysisClient

HTTP calls: requests
```bash
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
```
### Blob Trigger

- Watches the input/ container.
- kicks off the Durable orchestrator, passing in the filename.


```bash
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)
blob_svc = BlobServiceClient.from_connection_string(os.environ["BLOB_STORAGE_ENDPOINT"])

@app.blob_trigger(arg_name="myblob", path="input", connection="BLOB_STORAGE_ENDPOINT")
@app.durable_client_input(client_name="client")
async def blob_trigger(myblob: func.InputStream, client):
    logging.info(f"Trigger blob {myblob.name} ({myblob.length} bytes)")
    name = myblob.name.split("/")[-1]
    await client.start_new("orchestrator", client_input=name)

```
### Orchestrator

- analyze_pdf → extract raw text
- summarize_text → call OpenAI API
- write_summary → store .txt in output/

```bash
@app.orchestration_trigger(context_name="context")
def orchestrator(context):
    blob_name = context.get_input()
    opts = df.RetryOptions(first_retry_interval_in_milliseconds=5000,
                           max_number_of_attempts=3)

    text    = yield context.call_activity_with_retry("analyze_pdf", opts, blob_name)
    summary = yield context.call_activity_with_retry("summarize_text", opts, text)
    outblob = yield context.call_activity_with_retry("write_summary", opts,
                                                     {"blob": blob_name, "summary": summary})
    return outblob

```
### PDF → Text (analyze_pdf)

- Downloads the PDF bytes
- Calls Form Recognizer (prebuilt-layout)
- Joins all lines into one large text string


```bash
@app.activity_trigger(input_name="blobName")
def analyze_pdf(blobName):
    blob = blob_svc.get_container_client("input").get_blob_client(blobName)
    pdf_bytes = blob.download_blob().readall()

    recog = DocumentAnalysisClient(
        os.environ["COGNITIVE_SERVICES_ENDPOINT"],
        AzureKeyCredential(os.environ["COGNITIVE_SERVICES_KEY"])
    )
    poller = recog.begin_analyze_document("prebuilt-layout",
                                          document=pdf_bytes, locale="en-US")
    pages = poller.result().pages

    txt = "\n".join(
        line.content
        for p in pages
        for line in p.lines
    )
    return txt

```
### Text → Summary (summarize_text)

- Builds REST call to Azure OpenAI
- Posts the raw text as a single user message
- Extracts the GPT-generated summary

```bash
@app.activity_trigger(input_name="text")
def summarize_text(text: str):
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
    return resp.json()["choices"][0]["message"]["content"]

```
### Write Summary (write_summary)

- Names the file <original>.txt-<timestamp>
- Uploads the summary string to output/
```bash
@app.activity_trigger(input_name="input")
def write_summary(input: dict):
    blob_name = input["blob"]
    summary   = input["summary"]
    ts        = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    out_name  = f"{blob_name}-{ts}.txt"

    blob_svc.get_container_client("output")\
        .upload_blob(name=out_name, data=summary)
    return out_name

```
## function_app.py

```python
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

```

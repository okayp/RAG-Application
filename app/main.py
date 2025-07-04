from fastapi import FastAPI, UploadFile, Form
from pdfminer.high_level import extract_text
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import requests
import json
import re
import tempfile

app = FastAPI(title="NDA Clause Conflict Checker API")

# 1. Extract text from PDF
def extract_text_from_pdf(pdf_path):
    return extract_text(pdf_path)

# 2. Chunk text (RAG style)
def chunk_text(text, chunk_size=500, overlap=50):
    paragraphs = text.split('\n')
    chunks, current_chunk = [], ""

    for para in paragraphs:
        if not para.strip():
            continue
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += para + "\n"
        else:
            chunks.append(current_chunk.strip())
            current_chunk = para + "\n"
    if current_chunk:
        chunks.append(current_chunk.strip())

    final_chunks = []
    for i in range(len(chunks)):
        chunk = "\n".join(chunks[max(0, i-1):i+1])
        final_chunks.append(chunk)
    return final_chunks

# 3. Build vector store
def build_vector_store(chunks, embed_model):
    embeddings = embed_model.encode(chunks)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings))
    return index, embeddings, chunks

# 4. Retrieve top chunks
def retrieve_similar_chunks(query, embed_model, index, stored_chunks, k=5):
    query_vec = embed_model.encode([query])
    D, I = index.search(np.array(query_vec), k)
    return [stored_chunks[i] for i in I[0]]

# 5. Call Ollama LLM
def call_ollama_llm(prompt, model="ndamodel", temperature=0):
    response = requests.post(
        "http://host.docker.internal:11434/api/generate",
        json={"model": model, "prompt": prompt, "temperature": temperature, "stream": False}
    )
    response.raise_for_status()
    return response.json()["response"]

# 6. Format prompt
def format_prompt(new_clause, context_chunks):
    context = "\n\n".join(context_chunks)
    return f"""
You are a legal assistant. Determine if the following new clause conflicts with any parts of an NDA document.

[New Clause]
"{new_clause}"

[Relevant Sections from NDA]
{context}

Respond in JSON with:
- whether there is a conflict
- the clause or clauses in the document that the new clause conflicts with
- give reasons as to why the new clauses violates any of the existing clauses, if it does
- If there is a violation, rewrite the clause according to conform to NDA standards

Format:
{{
  "conflict": true/false,
  "violating_clause": ["..."],
  "reason": "...",
  "corrected_clause": "..."
}}
"""

# 7. Extract JSON safely
def extract_json(text):
    match = re.search(r'{.*}', text, re.DOTALL)
    return match.group(0) if match else None

@app.post("/check_clause_conflict/")
async def check_clause_conflict(
    file: UploadFile,
    new_clause: str = Form(...)
):
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Process the PDF
    raw_text = extract_text_from_pdf(tmp_path)
    chunks = chunk_text(raw_text)
    embed_model = SentenceTransformer('all-MiniLM-L6-v2')
    index, _, stored_chunks = build_vector_store(chunks, embed_model)
    top_chunks = retrieve_similar_chunks(new_clause, embed_model, index, stored_chunks)

    # Query LLM
    prompt = format_prompt(new_clause, top_chunks)
    llm_response = call_ollama_llm(prompt)

    # Extract JSON
    cleaned_json = extract_json(llm_response)
    if cleaned_json:
        return json.loads(cleaned_json)
    else:
        return {
            "error": "LLM response was not valid JSON",
            "raw_response": llm_response
        }

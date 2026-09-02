import json
import urllib.error
import urllib.request


OLLAMA_URL = "http://localhost:11434/api/chat"


class OllamaError(Exception):
    pass


def get_available_models():
    url = "http://localhost:11434/api/tags"

    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )
    except urllib.error.URLError as error:
        raise OllamaError(
            "Cannot connect to Ollama. Start Ollama first."
        ) from error

    return [
        model["name"]
        for model in data.get("models", [])
    ]


def chat(model, messages, temperature=0.2):
    request_data = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(request_data).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )
    except urllib.error.URLError as error:
        raise OllamaError(
            "Cannot connect to Ollama. Make sure Ollama is running."
        ) from error
    except TimeoutError as error:
        raise OllamaError(
            "The model took too long to respond."
        ) from error

    return data["message"]["content"].strip()


def summarize_text(model, text, instruction=None):
    instruction = instruction or (
        "Write a clear study summary. Include the key ideas, "
        "important findings, methods, and conclusions. "
        "Do not invent information that is not in the text."
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a careful academic assistant. "
                "Use only the supplied PDF text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{instruction}\n\n"
                f"PDF TEXT:\n{text}"
            ),
        },
    ]

    return chat(model, messages)


def chunk_text(text, chunk_size=7000):
    text = " ".join(text.split())

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        if end < len(text):
            paragraph_break = text.rfind(". ", start, end)

            if paragraph_break > start + (chunk_size // 2):
                end = paragraph_break + 1

        chunks.append(text[start:end])
        start = end

    return chunks


def summarize_document(model, text, progress_callback=None):
    chunks = chunk_text(text)

    if not chunks:
        raise OllamaError(
            "No selectable text was found in this PDF."
        )

    chunk_summaries = []

    for index, chunk in enumerate(chunks, start=1):
        if progress_callback is not None:
            progress_callback(index, len(chunks))

        chunk_summary = summarize_text(
            model=model,
            text=chunk,
            instruction=(
                "Summarize this section of a PDF for a student. "
                "Keep important facts, results, terminology, and "
                "conclusions."
            ),
        )

        chunk_summaries.append(
            f"SECTION {index} SUMMARY:\n{chunk_summary}"
        )

    combined = "\n\n".join(chunk_summaries)

    return summarize_text(
        model=model,
        text=combined,
        instruction=(
            "Create a final structured summary from these section "
            "summaries. Use headings: Overview, Key Points, "
            "Methods or Concepts, Important Results, and Conclusion. "
            "Keep it accurate and concise."
        ),
    )
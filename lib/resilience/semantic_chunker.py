#!/usr/bin/env python3
"""
lib/semantic_chunker.py

Accepts a file path and a task description, and prints the most semantically
relevant chunks of the file to stdout. Used by ralph.sh's context injection
to provide smarter, more focused context than 'cat'-ing the whole file.

This avoids wasting context window space on irrelevant boilerplate or unrelated
functions within a file.

Method:
1. Splits the file into overlapping chunks (e.g., 10 lines with 3 lines of overlap).
2. Uses a sentence-transformer model to create a vector embedding for the
   task description and for each code chunk.
3. Calculates the cosine similarity between the task description and each chunk.
4. Returns the top N chunks that have a similarity score above a certain
   threshold, up to a maximum total token count.

Requires:
- sentence-transformers
- torch
"""
import argparse
import sys
from typing import List

try:
    from sentence_transformers import SentenceTransformer, util
    import torch
except ImportError:
    print(
        "Error: Semantic chunking requires 'sentence-transformers' and 'torch'.\n"
        "Please install them: pip install sentence-transformers torch",
        file=sys.stderr,
    )
    sys.exit(1)

# Pre-trained model optimized for code retrieval tasks.
# Lightweight and effective.
MODEL_NAME = 'all-MiniLM-L6-v2'

# Configuration for chunking and selection
CHUNK_SIZE = 15  # lines per chunk
CHUNK_OVERLAP = 4 # lines of overlap between chunks
SIMILARITY_THRESHOLD = 0.25  # Minimum similarity score to be considered
MAX_CHUNKS = 10  # Return at most this many chunks


def create_chunks(lines: List[str], size: int, overlap: int) -> List[str]:
    """Splits a list of lines into overlapping chunks."""
    if not lines:
        return []

    chunks = []
    for i in range(0, len(lines), size - overlap):
        chunk = lines[i:i + size]
        if chunk:
            chunks.append("".join(chunk))
    return chunks

def main():
    parser = argparse.ArgumentParser(
        description="Extract semantically relevant code chunks from a file."
    )
    parser.add_argument(
        "--file", required=True, help="Path to the source code file."
    )
    parser.add_argument(
        "--task", required=True, help="The task description to match against."
    )
    args = parser.parse_args()

    try:
        with open(args.file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except FileNotFoundError:
        # Silently exit if file not found, as it might be a new file hint.
        sys.exit(0)
    except Exception as e:
        print(f"Error reading file {args.file}: {e}", file=sys.stderr)
        sys.exit(1)

    if not lines:
        sys.exit(0)

    # 1. Create text chunks
    chunks = create_chunks(lines, CHUNK_SIZE, CHUNK_OVERLAP)
    if not chunks:
        # If chunking fails, just print the whole file as a fallback
        print("".join(lines))
        sys.exit(0)

    # 2. Load model and create embeddings
    model = SentenceTransformer(MODEL_NAME)
    task_embedding = model.encode(args.task, convert_to_tensor=True)
    chunk_embeddings = model.encode(chunks, convert_to_tensor=True)

    # 3. Calculate cosine similarity
    cosine_scores = util.cos_sim(task_embedding, chunk_embeddings)[0]

    # 4. Select the best chunks
    top_results = torch.topk(cosine_scores, k=min(MAX_CHUNKS, len(chunks)), sorted=True)

    selected_chunks = []
    print(f"--- Relevant chunks from {args.file} ---
", file=sys.stderr)

    for i, (score, idx) in enumerate(zip(top_results.values, top_results.indices)):
        if score >= SIMILARITY_THRESHOLD:
            chunk_index = idx.item()
            start_line = max(0, chunk_index * (CHUNK_SIZE - CHUNK_OVERLAP))

            # To avoid printing overlapping chunks multiple times, we can add a check here,
            # but for now, we will just print them for simplicity.

            selected_chunks.append(chunks[chunk_index])
            print(f"Chunk {i+1} (score: {score:.2f}, lines ~{start_line+1}-{start_line+CHUNK_SIZE}):
{chunks[chunk_index]}
", file=sys.stderr)

    # 5. Print the selected chunks to stdout for capture by the shell script
    # We print them concatenated to form a coherent context block.
    if selected_chunks:
        print("
...
".join(selected_chunks))
    else:
        # If no chunks meet the threshold, maybe return the top one anyway?
        # For now, we return nothing, letting the process provide no context.
        print(f"No chunks from {args.file} met similarity threshold of {SIMILARITY_THRESHOLD}", file=sys.stderr)


if __name__ == "__main__":
    main()

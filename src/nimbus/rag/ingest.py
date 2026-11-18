import time

from dotenv import load_dotenv

from nimbus.rag.__main__ import CHUNKERS
from nimbus.rag.chunking import chunk_all
from nimbus.rag.corpus import load_policies
from nimbus.rag.pinecone_store import INDEXING_WAIT_S, ensure_index, ingest, open_index


def main() -> None:
    load_dotenv()
    ensure_index()
    index = open_index()
    docs = load_policies()
    for namespace, chunker in CHUNKERS.items():
        chunks = chunk_all(docs, chunker)
        ingest(index, namespace, chunks)
        print(f"{namespace}: {len(chunks)} chunks")
    print(f"Waiting {INDEXING_WAIT_S}s for indexing...")
    time.sleep(INDEXING_WAIT_S)


if __name__ == "__main__":
    main()

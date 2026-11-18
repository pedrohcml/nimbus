import argparse
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from nimbus.rag.chunking import Chunk, chunk_all, chunk_by_section, chunk_by_window
from nimbus.rag.corpus import load_policies
from nimbus.rag.evaluation import KS, average, evaluate, load_retrieval_cases
from nimbus.rag.pinecone_store import PineconeRetriever, open_index
from nimbus.rag.retrieval import BM25Retriever, Retriever

CHUNKERS = {"section": chunk_by_section, "window": chunk_by_window}
RETRIEVERS: dict[str, Callable[[str, list[Chunk]], Retriever]] = {
    "bm25": lambda _chunking, chunks: BM25Retriever(chunks),
    "pinecone": lambda chunking, chunks: PineconeRetriever(open_index(), chunking, chunks),
}
SUBSETS = ("all", "en", "pt")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Measure policy retrieval.")
    parser.add_argument("--cases", default="evals/retrieval/v0.yaml")
    args = parser.parse_args()

    cases = load_retrieval_cases(Path(args.cases))
    docs = load_policies()
    columns = [f"recall@{k}" for k in KS] + ["mrr"]
    print("| chunking | retriever | questions | " + " | ".join(columns) + " |")
    print("|---" * (3 + len(columns)) + "|")

    for chunk_name, chunker in CHUNKERS.items():
        chunks = chunk_all(docs, chunker)
        for retriever_name, make_retriever in RETRIEVERS.items():
            per_case = evaluate(make_retriever(chunk_name, chunks), cases)
            for subset in SUBSETS:
                selected = [
                    s
                    for s, c in zip(per_case, cases, strict=False)
                    if subset in ("all", c.language)
                ]
                scores = average(selected)
                values = " | ".join(f"{scores[name]:.2f}" for name in columns)
                print(
                    f"| {chunk_name} | {retriever_name} | {subset} ({len(selected)}) | {values} |"
                )


if __name__ == "__main__":
    main()

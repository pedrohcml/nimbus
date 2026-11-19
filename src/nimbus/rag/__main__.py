import argparse
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from nimbus.rag.chunking import Chunk, chunk_all, chunk_by_section, chunk_by_window
from nimbus.rag.corpus import load_policies
from nimbus.rag.evaluation import KS, average, load_retrieval_cases, score_case, search_all
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
    parser.add_argument("--cases", default="evals/retrieval/v1.yaml")
    parser.add_argument(
        "--misses", action="store_true", help="list questions not answered at rank 1"
    )
    args = parser.parse_args()

    cases = load_retrieval_cases(Path(args.cases))
    docs = load_policies()
    columns = [f"recall@{k}" for k in KS] + ["mrr"]
    print("| chunking | retriever | questions | " + " | ".join(columns) + " |")
    print("|---" * (3 + len(columns)) + "|")

    misses = []
    for chunk_name, chunker in CHUNKERS.items():
        chunks = chunk_all(docs, chunker)
        for retriever_name, make_retriever in RETRIEVERS.items():
            ranked_lists = search_all(make_retriever(chunk_name, chunks), cases)
            per_case = [
                score_case(ranked, case) for ranked, case in zip(ranked_lists, cases, strict=False)
            ]
            for subset in SUBSETS:
                selected = [
                    s for s, c in zip(per_case, cases, strict=True) if subset in ("all", c.language)
                ]
                scores = average(selected)
                values = " | ".join(f"{scores[name]:.2f}" for name in columns)
                print(
                    f"| {chunk_name} | {retriever_name} | {subset} ({len(selected)}) | {values} |"
                )
            misses.append((f"{chunk_name} / {retriever_name}", ranked_lists, per_case))

    if args.misses:
        for label, ranked_lists, per_case in misses:
            print(f"\n### Misses: {label}")
            for case, ranked, score in zip(cases, ranked_lists, per_case, strict=True):
                if score["recall@1"] == 1:
                    continue
                rank = f"{round(1 / score['mrr'])}" if score["mrr"] else ">5"
                expected = "; ".join(f"{a.policy}/{','.join(a.sections)}" for a in case.answers)
                got = ", ".join(chunk.id for chunk in ranked[:3])
                print(f"- {case.id} (rank {rank}): expected {expected} | got {got}")


if __name__ == "__main__":
    main()

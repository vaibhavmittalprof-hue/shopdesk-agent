from shopdesk.rag.chunking import load_policy_chunks

chunks = load_policy_chunks()
print(f"{len(chunks)} chunks\n")
print(f"{'id':<40}{'characters':>10}")
for chunk in chunks:
    print(f"{chunk.id:<40}{len(chunk.text):>10}")

print("\n--- what the search will index for one chunk ---")
example = next(c for c in chunks if c.id == "refund#refund-timing")
print(example.search_text)
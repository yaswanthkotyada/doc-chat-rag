"""
Stage 7 - Gemini Tool Definitions: services/tools/definitions.py

Declares FunctionDeclaration and Tool objects for Gemini manual function calling.
"""

from google.genai import types

SEARCH_DOCUMENTS_DECLARATION = types.FunctionDeclaration(
    name="search_documents",
    description=(
        "Search the indexed documents using hybrid vector and keyword search. "
        "Returns the most relevant chunks with unique result IDs (e.g. R1, R2). "
        "Always use focused keyword queries (2-5 terms)."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "query": types.Schema(
                type="STRING",
                description="The search query keywords, exact phrase, or identifier to find in documents."
            ),
            "top_k": types.Schema(
                type="INTEGER",
                description="Number of results to retrieve (1 to 10). Defaults to 5."
            ),
        },
        required=["query"],
    ),
)

READ_SURROUNDING_DECLARATION = types.FunctionDeclaration(
    name="read_surrounding",
    description=(
        "Read neighboring chunks immediately before or after a previously retrieved search result. "
        "Use when a table is cut off, a sentence continues across chunk boundaries, or more section context is needed."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "result_id": types.Schema(
                type="STRING",
                description="The result ID to expand (e.g. 'R1', 'R2') from a prior search_documents call."
            ),
            "before": types.Schema(
                type="INTEGER",
                description="Number of preceding chunks to read (0 to 2). Defaults to 1."
            ),
            "after": types.Schema(
                type="INTEGER",
                description="Number of succeeding chunks to read (0 to 2). Defaults to 1."
            ),
        },
        required=["result_id"],
    ),
)

LIST_DOCUMENTS_DECLARATION = types.FunctionDeclaration(
    name="list_documents",
    description=(
        "List all available documents in RAG mode with filenames, page counts, and total chunks. "
        "Cheap call to see which documents are available to search."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={},
    ),
)


def get_rag_tools() -> list[types.Tool]:
    """Return the list of Tools configured for RAG conversations."""
    return [
        types.Tool(
            function_declarations=[
                SEARCH_DOCUMENTS_DECLARATION,
                READ_SURROUNDING_DECLARATION,
                LIST_DOCUMENTS_DECLARATION,
            ]
        )
    ]


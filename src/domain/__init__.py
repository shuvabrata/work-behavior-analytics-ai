"""Shared, transport-free domain logic.

Modules here must not import aio_pika, neo4j, elasticsearch, sqlalchemy,
asyncpg, openai, langchain, mcp, matplotlib, or community — they are shared
by the API runtime, the UI runtime, and the connector runtimes.
"""

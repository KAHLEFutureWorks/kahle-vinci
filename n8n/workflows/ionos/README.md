# IONOS n8n workflow templates

The workflow files in `n8n/workflows/` are versioned import templates. The live n8n database is not stored in Git, so importing a template does not update already-running workflows automatically.

After importing a workflow:

- Configure credentials or environment variables in n8n. Do not commit API keys.
- Use `IONOS_API_KEY` for IONOS OpenAI-compatible calls.
- Use the OpenAI-compatible base URL `https://openai.inference.de-txl.ionos.com/v1`.
- LangChain OpenAI Chat/Embedding nodes reference an `openAiApi` credential named `IONOS OpenAI Compatible` and set `options.baseURL` to the IONOS endpoint. Create/map that credential in n8n with the IONOS API key and the same base URL before activating imported workflows.
- Default chat model: `mistralai/Mistral-Small-24B-Instruct`.
- Reasoning/agentic chat model: `openai/gpt-oss-120b`.
- Embedding model: `BAAI/bge-m3`.
- Retention workflows that call `owui-file-proxy` include an `Authorization: Bearer {{$env.OWUI_FILE_PROXY_API_KEY}}` placeholder. Set that env var or replace it with an n8n credential before activation.

Qdrant remains the local vector database. Because the embedding model changes to `BAAI/bge-m3`, all affected Qdrant collections must be reindexed after migration.

Legacy aggregate exports can still contain Ollama/LangChain node shapes. Prefer HTTP Request nodes against the IONOS OpenAI-compatible endpoints when creating versioned templates, unless a workflow is explicitly migrated and tested with n8n OpenAI-compatible LangChain credentials.

## Optional Local AI Summaries

PDF Pro supports private, local PDF summarization through Ollama.

The core PDF reader works without Ollama. AI summaries require
Ollama and an installed local model.

### Setup

1. Install Ollama from https://ollama.com
2. Download a recommended model:

   ```bash
   ollama pull qwen2.5:3b
   ```

3. Start Ollama if it is not already running:

   ```bash
   ollama serve
   ```

4. Open PDF Pro → AI Hub → Refresh models.
5. Select an installed model and choose a scope.

### Privacy

PDF text is sent to Ollama running locally on your own computer.
PDF Pro does not require an AI API key and does not upload PDF text
to a cloud AI service.
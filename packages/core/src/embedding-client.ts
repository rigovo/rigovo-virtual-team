'use strict';

/**
 * Embedding generation client.
 * Supports OpenAI text-embedding-3-small (default) and local
 * all-minilm-l6-v2 via a configurable endpoint.
 */

interface EmbeddingConfig {
  provider: 'openai' | 'local';
  apiKey?: string;
  baseUrl?: string;
  model?: string;
}

interface EmbeddingResponse {
  embedding: number[];
  model: string;
  tokenUsage: number;
}

/**
 * Generates vector embeddings for semantic memory search.
 * Falls back to zero-vector when no provider is configured,
 * allowing the system to degrade gracefully.
 */
export class EmbeddingClient {
  private readonly provider: 'openai' | 'local';
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly dimensions = 384;

  constructor(config?: EmbeddingConfig) {
    this.provider = config?.provider ?? 'openai';
    this.apiKey = config?.apiKey ?? process.env.OPENAI_API_KEY ?? '';
    this.model = config?.model ?? 'text-embedding-3-small';
    this.baseUrl = config?.baseUrl ?? 'https://api.openai.com/v1';
  }

  /** Generate embedding for a single text input. */
  async embed(text: string): Promise<EmbeddingResponse> {
    if (!this.apiKey && this.provider === 'openai') {
      return this.zeroVector();
    }

    try {
      return await this.callProvider(text);
    } catch {
      return this.zeroVector();
    }
  }

  /** Generate embeddings for multiple texts in a single batch. */
  async embedBatch(texts: string[]): Promise<EmbeddingResponse[]> {
    if (!this.apiKey && this.provider === 'openai') {
      return texts.map(() => this.zeroVector());
    }

    try {
      return await this.callProviderBatch(texts);
    } catch {
      return texts.map(() => this.zeroVector());
    }
  }

  private async callProvider(text: string): Promise<EmbeddingResponse> {
    const url = `${this.baseUrl}/embeddings`;
    const body = JSON.stringify({
      input: text,
      model: this.model,
      dimensions: this.dimensions,
    });

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.apiKey}`,
      },
      body,
    });

    if (!response.ok) {
      throw new Error(`Embedding request failed: ${response.status}`);
    }

    const data = (await response.json()) as {
      data: Array<{ embedding: number[] }>;
      model: string;
      usage: { total_tokens: number };
    };

    return {
      embedding: data.data[0]?.embedding ?? [],
      model: data.model,
      tokenUsage: data.usage.total_tokens,
    };
  }

  private async callProviderBatch(
    texts: string[],
  ): Promise<EmbeddingResponse[]> {
    const url = `${this.baseUrl}/embeddings`;
    const body = JSON.stringify({
      input: texts,
      model: this.model,
      dimensions: this.dimensions,
    });

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.apiKey}`,
      },
      body,
    });

    if (!response.ok) {
      throw new Error(`Batch embedding request failed: ${response.status}`);
    }

    const data = (await response.json()) as {
      data: Array<{ embedding: number[] }>;
      model: string;
      usage: { total_tokens: number };
    };

    const perTokenCost = Math.ceil(data.usage.total_tokens / texts.length);

    return data.data.map((item) => ({
      embedding: item.embedding,
      model: data.model,
      tokenUsage: perTokenCost,
    }));
  }

  private zeroVector(): EmbeddingResponse {
    return {
      embedding: new Array<number>(this.dimensions).fill(0),
      model: 'zero-fallback',
      tokenUsage: 0,
    };
  }
}

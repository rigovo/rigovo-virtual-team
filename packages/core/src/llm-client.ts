'use strict';

import type {
  LLMConfig,
  LLMMessage,
  LLMResponse,
  LLMTool,
} from './types/index.js';

interface LLMRequestPayload {
  model: string;
  messages: LLMMessage[];
  tools?: LLMTool[];
  temperature?: number;
  max_tokens?: number;
}

interface AnthropicRequestPayload {
  model: string;
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  system?: string;
  tools?: AnthropicTool[];
  temperature?: number;
  max_tokens: number;
}

interface AnthropicTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

interface AnthropicResponse {
  id: string;
  content: Array<{
    type: 'text' | 'tool_use';
    text?: string;
    id?: string;
    name?: string;
    input?: Record<string, unknown>;
  }>;
  usage: {
    input_tokens: number;
    output_tokens: number;
  };
}

interface OpenAIResponse {
  choices: Array<{
    message: {
      content: string | null;
      tool_calls?: Array<{
        id: string;
        function: { name: string; arguments: string };
      }>;
    };
  }>;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

/**
 * Stateless LLM HTTP client. Handles provider routing, request building,
 * and response parsing for Anthropic and OpenAI-compatible APIs.
 */
export class LLMClient {
  private readonly config: LLMConfig;

  constructor(config: LLMConfig) {
    if (!config.apiKey) {
      throw new Error('LLMClient: API key is required');
    }
    this.config = config;
  }

  /** Send a chat completion request and return a typed response. */
  async chat(
    messages: LLMMessage[],
    tools?: LLMTool[],
  ): Promise<LLMResponse> {
    if (this.config.provider === 'anthropic') {
      return this.chatAnthropic(messages, tools);
    }
    return this.chatOpenAI(messages, tools);
  }

  /** Anthropic Messages API (/v1/messages). */
  private async chatAnthropic(
    messages: LLMMessage[],
    tools?: LLMTool[],
  ): Promise<LLMResponse> {
    let systemPrompt: string | undefined;
    const filtered: Array<{ role: 'user' | 'assistant'; content: string }> = [];

    for (const msg of messages) {
      if (msg.role === 'system') {
        systemPrompt = msg.content;
      } else {
        filtered.push({
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
        });
      }
    }

    const payload: AnthropicRequestPayload = {
      model: this.config.model,
      messages: filtered,
      max_tokens: this.config.maxTokens ?? 4096,
    };

    if (systemPrompt) {
      payload.system = systemPrompt;
    }

    if (this.config.temperature !== undefined) {
      payload.temperature = this.config.temperature;
    }

    if (tools && tools.length > 0) {
      payload.tools = tools.map((t) => ({
        name: t.name,
        description: t.description ?? '',
        input_schema: (t.parameters ?? {}) as Record<string, unknown>,
      }));
    }

    const url = `${this.getBaseUrl()}/messages`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': this.config.apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Anthropic API error: ${response.status} ${body}`);
    }

    const data = (await response.json()) as AnthropicResponse;
    return this.parseAnthropicResponse(data);
  }

  /** OpenAI-compatible /chat/completions for OpenAI, Groq, Ollama. */
  private async chatOpenAI(
    messages: LLMMessage[],
    tools?: LLMTool[],
  ): Promise<LLMResponse> {
    const payload: LLMRequestPayload = {
      model: this.config.model,
      messages,
    };

    if (tools && tools.length > 0) {
      payload.tools = tools;
    }
    if (this.config.temperature !== undefined) {
      payload.temperature = this.config.temperature;
    }
    if (this.config.maxTokens !== undefined) {
      payload.max_tokens = this.config.maxTokens;
    }

    const url = `${this.getBaseUrl()}/chat/completions`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`LLM API error: ${response.status} ${body}`);
    }

    const data = (await response.json()) as OpenAIResponse;
    return this.parseOpenAIResponse(data);
  }

  private getBaseUrl(): string {
    if (this.config.baseUrl) {
      return this.config.baseUrl;
    }

    switch (this.config.provider) {
      case 'openai':
        return 'https://api.openai.com/v1';
      case 'anthropic':
        return 'https://api.anthropic.com/v1';
      case 'groq':
        return 'https://api.groq.com/openai/v1';
      case 'ollama':
        return 'http://localhost:11434/v1';
      default: {
        const exhaustive: never = this.config.provider;
        throw new Error(`Unknown LLM provider: ${exhaustive}`);
      }
    }
  }

  private parseAnthropicResponse(data: AnthropicResponse): LLMResponse {
    let content = '';
    const toolCalls: LLMResponse['toolCalls'] = [];

    for (const block of data.content) {
      if (block.type === 'text' && block.text) {
        content += block.text;
      }
      if (block.type === 'tool_use' && block.id && block.name) {
        toolCalls.push({
          id: block.id,
          name: block.name,
          arguments: JSON.stringify(block.input ?? {}),
        });
      }
    }

    return {
      content,
      usage: {
        promptTokens: data.usage.input_tokens,
        completionTokens: data.usage.output_tokens,
        totalTokens: data.usage.input_tokens + data.usage.output_tokens,
      },
      toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
    };
  }

  private parseOpenAIResponse(data: OpenAIResponse): LLMResponse {
    const choice = data.choices?.[0];
    if (!choice) {
      throw new Error('LLM API returned no choices');
    }

    const result: LLMResponse = {
      content: choice.message.content ?? '',
      usage: {
        promptTokens: data.usage.prompt_tokens,
        completionTokens: data.usage.completion_tokens,
        totalTokens: data.usage.total_tokens,
      },
    };

    const calls = choice.message.tool_calls;
    if (calls && calls.length > 0) {
      result.toolCalls = calls.map((call) => ({
        id: call.id,
        name: call.function.name,
        arguments: call.function.arguments,
      }));
    }

    return result;
  }
}

export default LLMClient;

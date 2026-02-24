'use strict';

import { EventEmitter } from 'eventemitter3';
import type { AgentMessage, MessageType } from './types/index.js';
import type { AgentRole } from './types/index.js';

/** Message with internal receive timestamp for ordering. */
export type MessageWithMetadata = AgentMessage & {
  _receivedAt: number;
};

export type ExternalCallback = (message: AgentMessage) => Promise<void> | void;
export type MessageHandler = (message: AgentMessage) => void;
export type Unsubscribe = () => void;

export interface MessageBusConfig {
  maxHistorySize?: number;
}

/** Subscription target — subscribe to all messages, a specific agent, task, or message type. */
export type SubscriptionTarget =
  | { channel: 'all' }
  | { channel: 'agent'; role: AgentRole }
  | { channel: 'task'; taskId: string }
  | { channel: 'type'; messageType: MessageType };

/**
 * Inter-agent communication backbone. Every message between agents
 * flows through this bus. Typed, logged, and observable.
 */
export class MessageBus {
  private emitter: EventEmitter<string>;
  private history: MessageWithMetadata[] = [];
  private maxHistorySize: number;
  private externalCallback: ExternalCallback | null = null;

  constructor(config: MessageBusConfig = {}) {
    this.emitter = new EventEmitter<string>();
    this.maxHistorySize = config.maxHistorySize ?? 1000;
  }

  /** Publish a message to the bus. Routes to all matching channels. */
  publish(message: AgentMessage): void {
    if (!message || !message.type) {
      throw new Error('MessageBus: Cannot publish a message without a type');
    }

    this.history.push({ ...message, _receivedAt: Date.now() });
    if (this.history.length > this.maxHistorySize) {
      this.history.shift();
    }

    this.emitter.emit('message', message);
    if ('from' in message) {
      this.emitter.emit(`agent:${message.from}`, message);
    }
    if ('taskId' in message) {
      this.emitter.emit(`task:${message.taskId}`, message);
    }
    this.emitter.emit(`type:${message.type}`, message);

    if (this.externalCallback) {
      try {
        this.externalCallback(message);
      } catch (error) {
        const detail = error instanceof Error ? error.message : 'unknown';
        console.warn(`MessageBus: External callback failed: ${detail}`);
      }
    }
  }

  /** Subscribe to messages matching a target. Returns an unsubscribe function. */
  on(target: SubscriptionTarget, handler: MessageHandler): Unsubscribe {
    if (!target || !target.channel) {
      throw new Error('MessageBus: Subscription target must include a channel');
    }
    const channel = this.resolveChannel(target);
    this.emitter.on(channel, handler);
    return () => { this.emitter.off(channel, handler); };
  }

  /** Wait for a specific message type on a task. Rejects on timeout. */
  waitFor(
    taskId: string,
    messageType: MessageType,
    timeoutMs: number,
  ): Promise<AgentMessage> {
    if (!taskId || !messageType) {
      return Promise.reject(new Error('MessageBus: taskId and messageType required'));
    }
    return new Promise((resolve, reject) => {
      let timer: NodeJS.Timeout | null = null;

      const unsubscribe = this.on({ channel: 'task', taskId }, (msg) => {
        if (msg.type === messageType) {
          if (timer) clearTimeout(timer);
          unsubscribe();
          resolve(msg);
        }
      });

      timer = setTimeout(() => {
        unsubscribe();
        reject(new Error(`Timeout waiting for ${messageType} on task ${taskId}`));
      }, timeoutMs);
    });
  }

  /** Set external callback for cloud sync / realtime updates. */
  setExternalCallback(callback: ExternalCallback): void {
    if (typeof callback !== 'function') {
      throw new Error('MessageBus: callback must be a function');
    }
    this.externalCallback = callback;
  }

  /** Get message history for a specific task. */
  getTaskHistory(taskId: string): AgentMessage[] {
    if (!taskId) {
      throw new Error('MessageBus: taskId is required for history lookup');
    }
    return this.history
      .filter((msg) => 'taskId' in msg && msg.taskId === taskId)
      .map(({ _receivedAt: _unused, ...msg }) => msg as AgentMessage);
  }

  /** Clear all listeners and history. */
  destroy(): void {
    this.emitter.removeAllListeners();
    this.history = [];
    this.externalCallback = null;
  }

  private resolveChannel(target: SubscriptionTarget): string {
    switch (target.channel) {
      case 'all': return 'message';
      case 'agent': return `agent:${target.role}`;
      case 'task': return `task:${target.taskId}`;
      case 'type': return `type:${target.messageType}`;
    }
  }
}

export default MessageBus;

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim() || isSubmitting) return;

    setIsSubmitting(true);
    try {
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description }),
      });
      const data = await res.json();
      router.push(`/task/${data.taskId}`);
    } catch {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4">
      <div className="w-full max-w-2xl">
        <div className="flex items-center gap-3 mb-12">
          <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">
            R
          </div>
          <span className="text-lg font-semibold tracking-tight">Rigovo Teams</span>
        </div>

        <h1 className="text-3xl font-semibold tracking-tight mb-2">
          What should we build?
        </h1>
        <p className="text-zinc-500 mb-8">
          Describe your task. The team will assemble and start working.
        </p>

        <form onSubmit={handleSubmit}>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Build a REST API with JWT authentication, user registration, login, and password reset endpoints..."
            rows={5}
            className="w-full px-4 py-3 rounded-xl bg-[#131319] border border-white/[0.06] text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 resize-none text-[15px] leading-relaxed"
          />
          <div className="flex items-center justify-between mt-4">
            <span className="text-xs text-zinc-600">
              {description.length > 0 ? `${description.length} chars` : ''}
            </span>
            <button
              type="submit"
              disabled={!description.trim() || isSubmitting}
              className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-all"
            >
              {isSubmitting ? 'Assembling...' : 'Start'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

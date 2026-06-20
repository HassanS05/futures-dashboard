"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";

export function AIInsights() {
  const { data: status } = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus });
  const mutation = useMutation({
    mutationFn: () =>
      api.ask("market", "Give me today's concise market briefing in 5 bullet points."),
  });

  return (
    <Card
      title="AI Market Briefing"
      delay={0.25}
      action={
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !status?.enabled}
          className="flex items-center gap-1.5 rounded-lg bg-accent-grad px-3 py-1.5 text-xs font-semibold text-canvas disabled:opacity-40"
        >
          <Sparkles size={13} />
          {mutation.isPending ? "Thinking…" : "Generate"}
        </button>
      }
    >
      {!status?.enabled && (
        <p className="text-sm text-muted">
          Add an AI key (Claude / OpenAI / Gemini) in the backend to enable the
          copilot.
        </p>
      )}
      {status?.enabled && !mutation.data && !mutation.isPending && (
        <div className="flex items-center gap-3 py-6 text-muted">
          <Bot className="text-accent" />
          <p className="text-sm">
            Click <span className="text-text">Generate</span> for an AI summary of
            today's markets, powered by your portfolio context.
          </p>
        </div>
      )}
      {mutation.isPending && (
        <div className="space-y-2 py-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-4 w-full" />
          ))}
        </div>
      )}
      {mutation.data && (
        <div className="prose prose-invert prose-sm max-w-none whitespace-pre-wrap text-sm text-text/90">
          {mutation.data.content}
          <p className="mt-3 text-xs text-muted">
            via {mutation.data.provider} · {mutation.data.model_used}
          </p>
        </div>
      )}
      {mutation.isError && (
        <p className="text-sm text-down">Could not reach the AI service.</p>
      )}
    </Card>
  );
}

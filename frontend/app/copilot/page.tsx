"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Bot,
  PieChart,
  Repeat,
  Microscope,
  Newspaper,
  BookOpen,
  Send,
} from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";

const AGENTS = [
  { id: "portfolio", name: "Portfolio AI", icon: PieChart, desc: "Diversification, risk & rebalancing" },
  { id: "dca", name: "DCA AI", icon: Repeat, desc: "Optimise accumulation & projections" },
  { id: "research", name: "Crypto Research AI", icon: Microscope, desc: "Fundamentals, tokenomics & scoring" },
  { id: "market", name: "Market AI", icon: Newspaper, desc: "Daily briefing & opportunities" },
  { id: "journal", name: "Trading Journal AI", icon: BookOpen, desc: "Performance & discipline review" },
];

export default function CopilotPage() {
  const [agent, setAgent] = useState("portfolio");
  const [prompt, setPrompt] = useState("");
  const { data: status } = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus });
  const mutation = useMutation({ mutationFn: () => api.ask(agent, prompt) });

  const active = AGENTS.find((a) => a.id === agent)!;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">AI Copilot</h1>
        <p className="text-sm text-muted">
          Five specialised agents · multi-model routing (Claude · OpenAI · Gemini)
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <div className="space-y-2">
          {AGENTS.map((a) => {
            const Icon = a.icon;
            const sel = a.id === agent;
            return (
              <button
                key={a.id}
                onClick={() => setAgent(a.id)}
                className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-all ${
                  sel
                    ? "border-accent/40 bg-surface-2 shadow-glow"
                    : "border-border bg-surface/50 hover:bg-surface-2/60"
                }`}
              >
                <Icon size={18} className={sel ? "text-accent" : "text-muted"} />
                <div>
                  <p className="text-sm font-medium">{a.name}</p>
                  <p className="text-xs text-muted">{a.desc}</p>
                </div>
              </button>
            );
          })}
        </div>

        <Card className="flex min-h-[460px] flex-col">
          <div className="mb-4 flex items-center gap-2 border-b border-border/60 pb-3">
            <active.icon className="text-accent" size={18} />
            <span className="font-medium">{active.name}</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {!status?.enabled && (
              <p className="text-sm text-muted">
                No AI provider configured. Add an API key in the backend `.env`.
              </p>
            )}
            {mutation.isPending && (
              <div className="space-y-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="skeleton h-4 w-full" />
                ))}
              </div>
            )}
            {mutation.data && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="whitespace-pre-wrap text-sm text-text/90"
              >
                {mutation.data.content}
                <p className="mt-4 text-xs text-muted">
                  via {mutation.data.provider} · {mutation.data.model_used}
                </p>
              </motion.div>
            )}
            {!mutation.data && !mutation.isPending && status?.enabled && (
              <div className="flex h-full items-center justify-center text-muted">
                <Bot className="mr-2 text-accent" /> Ask {active.name} anything.
              </div>
            )}
          </div>

          <div className="mt-4 flex gap-2">
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && prompt && mutation.mutate()}
              placeholder={`Ask ${active.name}…`}
              className="flex-1 rounded-xl border border-border bg-surface/60 px-4 py-2.5 text-sm focus:border-accent/50 focus:outline-none"
            />
            <button
              onClick={() => mutation.mutate()}
              disabled={!prompt || mutation.isPending || !status?.enabled}
              className="flex items-center gap-1.5 rounded-xl bg-accent-grad px-4 py-2.5 text-sm font-semibold text-canvas disabled:opacity-40"
            >
              <Send size={15} /> Send
            </button>
          </div>
        </Card>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { ArrowUpRight, BookOpen, Building2, Globe2, Search, ShoppingCart, TrendingUp } from "lucide-react";

import { ToolPage, useAsk } from "@/components/tools/shared";

const LIBRARY: { group: string; icon: React.ReactNode; prompts: string[] }[] = [
  {
    group: "Geography",
    icon: <Globe2 size={15} />,
    prompts: [
      "Show the number of companies per country",
      "Which country has the highest total HR tech spend?",
      "Show the number of customers per country",
      "Which country does Professional Services Company 001 belong to?",
      "Compare average HR tech spend in India, Germany and Canada",
    ],
  },
  {
    group: "Companies & HR tech",
    icon: <Building2 size={15} />,
    prompts: [
      "Compare the average annual HR technology spend by deployment type",
      "Which HR technologies are used by the most companies? Show the top 8",
      "Total HR tech spend by industry",
      "Which industries have the largest average employee count?",
    ],
  },
  {
    group: "Sales & orders",
    icon: <ShoppingCart size={15} />,
    prompts: [
      "How many orders are there in each order status?",
      "Show the number of products per category",
      "What is the average order quantity per product?",
    ],
  },
  {
    group: "Trends",
    icon: <TrendingUp size={15} />,
    prompts: [
      "Show total revenue per month in 2024 from sales",
      "Which month had the highest revenue?",
      "How many customers signed up per month?",
    ],
  },
];

export function PromptsPage() {
  const ask = useAsk();
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();

  return (
    <ToolPage
      icon={<BookOpen size={13} />}
      eyebrow="Prompt library"
      title="Start from a proven question"
      description="Curated questions that work well with your data. Click one to open it in a new chat."
    >
      <label className="qc-search">
        <Search size={15} />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search prompts…" />
      </label>
      <div className="qc-prompt-groups">
        {LIBRARY.map((group) => {
          const prompts = group.prompts.filter((p) => !needle || p.toLowerCase().includes(needle));
          if (!prompts.length) return null;
          return (
            <section key={group.group} className="qc-prompt-group">
              <h2 className="qc-section-title">
                {group.icon} {group.group}
              </h2>
              <div className="qc-prompt-grid">
                {prompts.map((prompt) => (
                  <button key={prompt} type="button" className="qc-prompt-card" onClick={() => ask(prompt)}>
                    <span>{prompt}</span>
                    <ArrowUpRight size={15} />
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </ToolPage>
  );
}

"use client";

import { useState } from "react";
import { Database, Hash, Search, Table2, Type } from "lucide-react";

import { AskButton, LoadState, ToolPage, useApi } from "@/components/tools/shared";

type Field = { name: string; type: string; samples: Record<string, unknown>[] };
type Collection = { name: string; documents: number; fields: Field[] };

const NUMERIC = new Set(["int", "float", "Int64", "Decimal128"]);

function sampleText(field: Field) {
  return field.samples
    .map((sample) => sample[field.name])
    .filter((value) => value != null)
    .map((value) => (typeof value === "object" ? JSON.stringify(value) : String(value)))
    .slice(0, 3)
    .join(" · ");
}

export function CatalogPage() {
  const { data, error, loading, reload } = useApi<{ collections: Collection[] }>("/api/catalog");
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const collections = (data?.collections ?? []).filter(
    (c) => !needle || c.name.toLowerCase().includes(needle) || c.fields.some((f) => f.name.toLowerCase().includes(needle)),
  );

  return (
    <ToolPage
      icon={<Database size={13} />}
      eyebrow="Data catalog"
      title="What you can ask about"
      description="Every collection and field the chatbot is allowed to read. Sample values are PII-masked."
    >
      <label className="qc-search">
        <Search size={15} />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter collections or fields…" />
      </label>
      <LoadState loading={loading} error={error} onRetry={reload} />
      <div className="qc-catalog">
        {collections.map((collection) => (
          <article key={collection.name} className="qc-tile qc-catalog__item">
            <header className="qc-tile__head">
              <h2 className="qc-tile__title">
                <Table2 size={15} /> {collection.name}
              </h2>
              <span className="qc-pill">{collection.documents.toLocaleString()} docs</span>
            </header>
            <ul className="qc-catalog__fields">
              {collection.fields.map((field) => (
                <li key={field.name} className={needle && field.name.toLowerCase().includes(needle) ? "is-match" : ""}>
                  <span className="qc-catalog__type" title={field.type}>
                    {NUMERIC.has(field.type) ? <Hash size={12} /> : <Type size={12} />}
                  </span>
                  <code>{field.name}</code>
                  <span className="qc-catalog__sample">{sampleText(field)}</span>
                </li>
              ))}
            </ul>
            <footer className="qc-catalog__foot">
              <AskButton prompt={`Give me an overview of the ${collection.name} collection with key statistics`} label="Overview" />
            </footer>
          </article>
        ))}
      </div>
    </ToolPage>
  );
}

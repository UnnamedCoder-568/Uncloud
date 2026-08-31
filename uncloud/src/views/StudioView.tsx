import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { getLibrary } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';

export default function StudioView({
  title, subtitle, categories, placeholder,
}: {
  title: string;
  subtitle: string;
  categories: string[];
  placeholder: string;
}) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [prompt, setPrompt] = useState('');

  useEffect(() => {
    getLibrary().then((list) => setModels(list.filter((m) => categories.includes(m.category))));
  }, [categories.join(',')]);

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <h1 className="text-2xl font-semibold mb-1">{title}</h1>
      <p className="text-xs text-[var(--text-faint)] mb-6">{subtitle}</p>

      <div className="max-w-xl card p-5">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className="w-full bg-transparent outline-none resize-none text-sm placeholder:text-[var(--text-faint)]"
        />
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--border-soft)]">
          <span className="text-[11px] text-[var(--text-faint)]">
            {models.length > 0 ? `${models.length} model(s) installed` : 'No models installed yet — see the Models tab'}
          </span>
          <button
            disabled
            title="Generation pipeline lands in the next build"
            className="flex items-center gap-1.5 text-[11px] bg-[var(--border)] text-[var(--text-faint)] px-3 py-1.5 rounded-full cursor-not-allowed"
          >
            <Sparkles size={12} /> Generate
          </button>
        </div>
      </div>

      <div className="max-w-xl mt-4 text-[11px] text-[var(--text-faint)] leading-relaxed">
        The generation pipeline for this tab isn't wired up yet — model download and detection work today,
        inference is next.
      </div>
    </div>
  );
}

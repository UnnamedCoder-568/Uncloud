import type { ResidentModels } from '../lib/sidecar';

export default function ResidentModelList({ resident }: { resident: ResidentModels }) {
  const rows: NonNullable<ResidentModels['models']> = resident.models ?? ([
    ['Chat', resident.text_model], ['Image', resident.image_pipeline],
    ['Image (MLX)', resident.mflux_model], ['Image (assembled)', resident.flux2_profile],
    ['Video', resident.video_pipeline],
  ] as [string, string | null][]).filter(([, path]) => path)
    .map(([kind, path]) => ({ kind, path: String(path) }));
  return <ul className="text-xs text-[var(--text-dim)] font-mono leading-relaxed">
    {rows.map(({ kind, path, device, context_limit }, index) => <li
      key={`${kind}:${path}:${index}`} className="truncate" title={path}>
      <span className="text-[var(--text-faint)]">{kind}: </span>
      {String(path).split(/[\\/]/).pop()}
      {device && <span className="block faint">{device}
        {context_limit ? ` · ${context_limit.toLocaleString()} context tokens` : ''}
      </span>}
    </li>)}
    {resident.speech_workers > 0 && <li>Voice: {resident.speech_workers} active workers</li>}
    {resident.music_jobs > 0 && <li>Music: {resident.music_jobs} active jobs</li>}
    {resident.narration_jobs > 0 && <li>Narration: {resident.narration_jobs} active jobs</li>}
  </ul>;
}

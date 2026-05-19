"use client";

import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { usePersonaApi } from "@/lib/api/persona";

type DropProps = {
  label: string;
  file: File | null;
  getRootProps: ReturnType<typeof useDropzone>["getRootProps"];
  getInputProps: ReturnType<typeof useDropzone>["getInputProps"];
  isDragActive: boolean;
};

function DropZone({ label, file, getRootProps, getInputProps, isDragActive }: DropProps) {
  return (
    <div>
      <label className="block text-sm text-[color:var(--color-text)] mb-1.5">{label}</label>
      <div
        {...getRootProps()}
        className={`rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition ${
          isDragActive
            ? "border-primary bg-[color:var(--color-surface-2)]"
            : "border-[color:var(--color-border-2)] hover:border-primary/60"
        }`}
      >
        <input {...getInputProps()} />
        {file ? (
          <div className="text-sm text-[color:var(--color-text)]">
            <span className="text-primary">✓</span> {file.name} ({(file.size / 1024).toFixed(0)} KB)
          </div>
        ) : (
          <div className="text-sm text-[color:var(--color-text-muted)]">
            Drop a PDF here, or click to browse
          </div>
        )}
      </div>
    </div>
  );
}

export function UploadStep({ onComplete }: { onComplete: () => void }) {
  const api = usePersonaApi();
  const [resume, setResume] = useState<File | null>(null);
  const [linkedin, setLinkedin] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resumeDrop = useDropzone({
    onDrop: ([f]) => f && setResume(f),
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });
  const linkedinDrop = useDropzone({
    onDrop: ([f]) => f && setLinkedin(f),
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });

  async function submit() {
    if (!resume && !linkedin) {
      setError("Upload at least one PDF");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.uploadPdfs({ resume: resume ?? undefined, linkedin: linkedin ?? undefined });
      onComplete();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">
          Upload your resume + LinkedIn export
        </h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          PDFs only. We parse text out and never share these files.
        </p>
      </div>

      <DropZone
        label="Resume PDF (required)"
        file={resume}
        {...resumeDrop}
      />
      <DropZone
        label="LinkedIn export PDF (optional but recommended)"
        file={linkedin}
        {...linkedinDrop}
      />

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      <button
        onClick={submit}
        disabled={busy || (!resume && !linkedin)}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
      >
        {busy ? "Uploading..." : "Upload & continue"}
      </button>
    </div>
  );
}

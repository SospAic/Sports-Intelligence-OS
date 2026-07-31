"use client";

/* eslint-disable @next/next/no-img-element -- arbitrary platform media needs a native loading fallback */

import { useState, type ReactNode } from "react";

import { normalizeExternalImageUrl } from "@/lib/media";

type ExternalImageProps = {
  src: string | null | undefined;
  alt: string;
  className?: string;
  containerClassName?: string;
  children?: ReactNode;
  loading?: "eager" | "lazy";
};

export function ExternalImage({
  src,
  alt,
  className,
  containerClassName,
  children,
  loading = "lazy",
}: ExternalImageProps) {
  const normalized = normalizeExternalImageUrl(src);
  const [failedSource, setFailedSource] = useState<string | null>(null);

  if (!normalized || failedSource === normalized) return null;

  const image = (
    <img
      src={normalized}
      alt={alt}
      className={className}
      loading={loading}
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailedSource(normalized)}
    />
  );

  if (containerClassName) {
    return (
      <div className={containerClassName}>
        {image}
        {children}
      </div>
    );
  }
  return image;
}

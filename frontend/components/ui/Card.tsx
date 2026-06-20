"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({
  children,
  className,
  title,
  action,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  action?: ReactNode;
  delay?: number;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: [0.22, 1, 0.36, 1] }}
      className={cn("glass p-5", className)}
    >
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between">
          {title && (
            <h3 className="text-sm font-semibold tracking-wide text-muted">{title}</h3>
          )}
          {action}
        </header>
      )}
      {children}
    </motion.section>
  );
}

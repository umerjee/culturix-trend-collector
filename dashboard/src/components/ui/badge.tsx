import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        twitter: "border-transparent bg-sky-100 text-sky-700",
        tiktok: "border-transparent bg-pink-100 text-pink-700",
        youtube: "border-transparent bg-red-100 text-red-700",
        reddit: "border-transparent bg-orange-100 text-orange-700",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function PlatformBadge({ platform }: { platform: string }) {
  const v = platform as "twitter" | "tiktok" | "youtube" | "reddit";
  const labels: Record<string, string> = {
    twitter: "𝕏 Twitter",
    tiktok: "TikTok",
    youtube: "YouTube",
    reddit: "Reddit",
  };
  return <Badge variant={v}>{labels[platform] ?? platform}</Badge>;
}

export { Badge, badgeVariants };

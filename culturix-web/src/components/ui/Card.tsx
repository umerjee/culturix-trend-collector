import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

// Standardizes the `rounded-2xl border border-gray-100 bg-white` shell used
// ad hoc across dashboard/admin/marketing cards. CardHeader/CardBody are
// optional — plenty of existing cards just use a single padded div.
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-gray-100 bg-white", className)} {...props} />;
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pt-5 pb-3", className)} {...props} />;
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}

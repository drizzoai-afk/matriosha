"use client";

import Link from "next/link";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function QuickActionsMenu() {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground">Fast links for account operations.</p>
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button variant="outline" />}>
          <MoreHorizontal className="size-4" />
          Actions
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuItem render={<Link href="/api/billing" />}>Billing</DropdownMenuItem>
          <DropdownMenuItem render={<Link href="mailto:drizzo.ai@gmail.com" />}>Support</DropdownMenuItem>
          <DropdownMenuItem render={<Link href="https://github.com/drizzoai-afk/matriosha" target="_blank" />}>GitHub</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

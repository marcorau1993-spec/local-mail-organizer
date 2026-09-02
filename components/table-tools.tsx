'use client';

import { ArrowDown, ArrowUp, ArrowUpDown, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableHead } from '@/components/ui/table';

export type SortDirection = 'asc' | 'desc';
export type SortValue = string | number | boolean | null | undefined;

export function filterAndSort<T>(
  rows: T[],
  query: string,
  searchText: (row: T) => string,
  value: (row: T) => SortValue,
  direction: SortDirection,
) {
  const needle = query.trim().toLocaleLowerCase();
  return rows
    .filter(
      (row) => !needle || searchText(row).toLocaleLowerCase().includes(needle),
    )
    .map((row, index) => ({ row, index, value: value(row) }))
    .sort((a, b) => {
      const left = a.value ?? '';
      const right = b.value ?? '';
      const comparison =
        typeof left === 'number' && typeof right === 'number'
          ? left - right
          : String(left).localeCompare(String(right), undefined, {
              numeric: true,
              sensitivity: 'base',
            });
      return (
        (direction === 'asc' ? comparison : -comparison) || a.index - b.index
      );
    })
    .map(({ row }) => row);
}

export function nextSort(
  currentKey: string,
  direction: SortDirection,
  key: string,
) {
  return {
    key,
    direction:
      currentKey === key && direction === 'asc'
        ? ('desc' as const)
        : ('asc' as const),
  };
}

export function TableFilterBar({
  value,
  onChange,
  shown,
  total,
  placeholder = 'Filter table…',
}: {
  value: string;
  onChange: (value: string) => void;
  shown: number;
  total: number;
  placeholder?: string;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <div className="relative min-w-60 flex-1 sm:max-w-md">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          size={16}
        />
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="pl-9 pr-9"
          aria-label={placeholder}
        />
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            className="absolute right-2 top-1/2 -translate-y-1/2"
            onClick={() => onChange('')}
            aria-label="Clear table filter"
          >
            <X />
          </Button>
        )}
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">
        {shown.toLocaleString()} of {total.toLocaleString()} rows
      </span>
    </div>
  );
}

export function SortableTableHead({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
  className,
}: {
  label: string;
  sortKey: string;
  activeKey: string;
  direction: SortDirection;
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = activeKey === sortKey;
  const Icon = !active
    ? ArrowUpDown
    : direction === 'asc'
      ? ArrowUp
      : ArrowDown;
  return (
    <TableHead
      className={className}
      aria-sort={
        active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'
      }
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex w-full items-center gap-1.5 font-medium hover:text-foreground ${className?.includes('text-right') ? 'justify-end' : ''}`}
      >
        {label}
        <Icon
          size={14}
          className={active ? 'text-primary' : 'text-muted-foreground'}
        />
      </button>
    </TableHead>
  );
}

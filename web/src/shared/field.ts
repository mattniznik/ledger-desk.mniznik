// Sizes of the marks in the dot field (How.tsx, Field), from the grid step ("pitch"). From the sibling demo.
//
// A lit mark stands out by colour and a modest size step, and always fits inside its own cell (shared/how.test.ts).

export type MarkSizes = {
  dot: number; // radius of a plain grid dot
  lit: number; // radius of a lit PDF bill
  pulse: number; // largest radius while a dot is lighting up
  square: number; // side of a lit phone photo
};

export function markSizes(pitch: number): MarkSizes {
  const dot = Math.max(1.6, pitch * 0.3);
  return {
    dot,
    lit: Math.min(dot * 1.35, pitch * 0.42),
    pulse: Math.min(dot * 1.5, pitch * 0.45),
    square: Math.min(dot * 2.4, pitch * 0.8),
  };
}

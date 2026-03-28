import { PropsWithChildren } from "react";

interface CardProps extends PropsWithChildren {
  className?: string;
}

export default function Card({ className = "", children }: CardProps) {
  return <section className={`card ${className}`.trim()}>{children}</section>;
}

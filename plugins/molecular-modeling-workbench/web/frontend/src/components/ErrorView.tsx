import type { ReceiptError } from "../api/types";
import { humanizeError } from "../lib/errors";

export interface ErrorViewProps {
    receipt: ReceiptError | null | undefined;
}

export function ErrorView({ receipt }: ErrorViewProps) {
    if (!receipt) return null;
    const error = humanizeError(receipt);
    return (
        <section className="error-view" data-testid="error-view" role="alert">
            <h3 data-testid="error-title">{error.title}</h3>
            <p data-testid="error-detail">{error.detail}</p>
            <ul>
                {error.suggestions.map((suggestion, index) => (
                    <li key={index} data-testid="error-suggestion">
                        {suggestion}
                    </li>
                ))}
            </ul>
        </section>
    );
}

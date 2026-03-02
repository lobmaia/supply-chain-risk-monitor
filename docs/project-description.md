# Supply Chain Risk Monitor: Project Description and Requirements

## Project Description
The Supply Chain Risk Monitor is a data-driven application designed to help operations and procurement teams identify potential supply chain disruptions earlier. The project focuses on monitoring external signals, especially news coverage, and translating those signals into practical risk insights for specific companies, regions, and commodities.

In practice, the application continuously collects headlines and articles, filters out noise, and highlights events that may indicate disruption risk, such as port strikes, regulatory changes, geopolitical tensions, factory shutdowns, or natural disasters. Instead of presenting raw data, it provides an interpretable view of risk over time so users can quickly understand what changed, why it changed, and where attention is needed.

The intended users are supply chain analysts, procurement teams, and operations managers who need a lightweight, explainable monitoring tool rather than a fully integrated enterprise platform.

## Project Requirements
The project requires an end-to-end workflow that starts with data ingestion and ends with a usable risk dashboard.

### Data and Processing Requirements
- The system needs at least one reliable news input source (for example, NewsAPI, GDELT, or curated RSS feeds).
- It should filter for supply-chain relevance so unrelated articles do not dominate outputs.
- Relevant content should be tagged to entities such as company, region, and commodity/product category.
- Each relevant item should receive a risk score, and item scores should roll up into entity-level risk indicators.
- The application should track risk trends over time and flag notable negative spikes.

### Product and UX Requirements
- The dashboard should show current risk levels for monitored entities.
- It should include a timeline view to make trend changes visible.
- It should present flagged headlines and clearly connect them to risk signals.
- Alerts should be explainable, with source evidence available to the user.
- Users should be able to configure and update watchlists without code changes.

### Quality Requirements
- Outputs should be traceable to source articles for auditability.
- The pipeline should handle transient ingestion or processing failures reasonably well.
- The interface should remain understandable for users without ML expertise.
- Secrets such as API keys should be handled securely.

## MVP Focus
The MVP is a functional, explainable monitoring product that demonstrates core value quickly.

### MVP Includes
- One working news ingestion source.
- Relevance filtering and basic entity tagging.
- Article-level and entity-level risk scoring.
- Trend visualization for monitored entities.
- Dashboard views for risk summary, flagged headlines, and supporting evidence.
- Configurable watchlist management.

### MVP Excludes (Initial Version)
- External shipping/vessel data integration (for example, MarineTraffic).
- Full alert-channel implementation (email/SMS/Slack).
- Historical backtesting module.
- Advanced custom model training and fine-tuning.

## Success Criteria
The project is successful if it consistently surfaces meaningful disruption-related signals, shows risk movement over time, and provides enough explanation for analysts to trust and act on alerts.

## Future Expansion
After MVP validation, the project can expand to include shipping/trade data sources, richer alerting channels, historical backtesting against known disruptions, and model improvements for better precision and multilingual coverage.


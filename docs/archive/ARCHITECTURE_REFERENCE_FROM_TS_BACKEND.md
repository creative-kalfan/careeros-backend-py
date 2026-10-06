# Architecture Reference: TypeScript Backend Design Patterns

This document captures the key architectural patterns, design decisions, and structural ideas from the TypeScript backend that have genuine design value worth preserving for future reference.

## Event Bus System

The TypeScript backend implemented a sophisticated typed domain event system that decouples side effects from the actions that trigger them. The event bus architecture includes:

- **Typed Domain Events**: Strongly-typed events with specific payload structures for different business domains
- **Publish/Dispatch Pipeline**: Events are published to a central bus, then dispatched to registered subscribers
- **Per-Subscriber Delivery Tracking**: Each event delivery to individual subscribers is tracked separately with status (pending, processing, processed, failed)
- **Retry Queue with Dead-Letter Handling**: Failed event deliveries are automatically retried with exponential backoff, and persistent failures are moved to a dead-letter queue for manual intervention
- **Event Replay Capability**: The system supports replaying historical events for debugging or rebuilding state

This pattern enables loose coupling between components while maintaining reliability through comprehensive tracking and retry mechanisms. It's particularly valuable for systems that need to grow and scale, as it allows new features to be added as event subscribers without modifying core business logic.

## Notification Engine Pipeline

The notification system implements a multi-stage processing pipeline designed to avoid spamming users:

1. **Preference Check**: User notification preferences are consulted first to determine if a notification should be sent
2. **Template Resolution**: Notification content is generated from templates based on the event type and payload
3. **Channel Resolution**: Delivery channels (in-app, email, push) are determined based on user preferences
4. **Queue with Quiet Hours**: Notifications are queued and respect user-defined quiet hours to avoid interruptions
5. **Dispatch with Rate Limiting**: Actual delivery is handled with rate limiting and error handling
6. **Digest Batching**: Multiple notifications can be batched into daily/weekly digests

The quiet hours scheduling and digest batching are particularly important for user experience, preventing notification fatigue while ensuring important information still reaches users in a timely manner.

## Recommendation Engine Batch Processing

The recommendation system uses a matrix processing pattern for generating personalized job recommendations:

- **Batch Jobs × Users Matrix**: The engine processes jobs in batches against users in batches, creating a matrix of potential recommendations
- **Observability Table Design**: A dedicated `recommendation_runs` table tracks the status, duration, and logs of each batch processing run
- **Incremental Processing**: Large datasets are processed in manageable chunks (configurable batch sizes)
- **Comprehensive Logging**: Each run captures detailed metrics including jobs processed, users processed, recommendations generated, and any errors encountered

This pattern is essential for long-running batch jobs as it provides visibility into progress, helps with debugging failures, and allows for resuming interrupted processes. The observability table serves as both an operational log and a performance monitoring tool.

## ATS Scoring Facade with Graceful Degradation

The ATS (Applicant Tracking System) scoring service implements a reusable pattern for handling optional external dependencies:

- **Primary/Secondary Service Pattern**: Prefers an external NLP microservice for high-quality analysis
- **Automatic Fallback**: When the NLP service is unavailable (health check fails), it gracefully falls back to a heuristic scoring algorithm
- **Unified Interface**: Both services implement the same interface, so consumers don't need to know which implementation is being used
- **Health Monitoring**: Continuous health checks ensure the system can detect and respond to service outages automatically

This graceful degradation pattern is valuable for any system that depends on external services that may be intermittently available. It ensures the system remains functional even when preferred services are down.

## Resume Parsing Pipeline

The resume processing system implements a structured extraction and versioning pipeline:

1. **Extract**: Raw text is extracted from various file formats (PDF, DOCX) using format-specific extractors
2. **Parse**: The raw text is parsed into structured data with identified sections (education, experience, skills)
3. **Map to Structured JSON**: Parsed data is mapped to a standardized JSON schema for consistent storage and processing
4. **Persist with Versioning**: Each parsing operation creates a new version, allowing users to track changes over time

The versioning system is particularly important as users frequently update and re-upload resumes. Maintaining a history allows for comparison, rollback, and tracking of improvements over time.

## Database Schema Evolution

The database schema evolved through several key migrations that reflect the system's growth:

- **Migration 001**: Initial schema with core entities (profiles, resumes, ATS reports, applications) and RLS policies
- **Migration 002**: Added resume parsing capabilities with versioning support
- **Migration 003**: Introduced the ATS engine with detailed scoring metrics
- **Migration 004**: Expanded job platform features for job tracking and management
- **Migration 005**: Added the recommendation engine with batch processing support
- **Migration 006**: Implemented the notification engine with preference management
- **Migration 007**: Introduced the internal event bus with comprehensive tracking tables
- **Migration 008**: Added profile completion tracking and resume metadata
- **Migration 009**: Enhanced profile role management
- **Migration 010**: Added company-ATS mapping capabilities
- **Migration 011**: Introduced job classification features

This evolution shows how the system grew from basic resume management to a comprehensive career optimization platform, with each migration adding specific capabilities while maintaining backward compatibility.

## Key Design Principles

Several cross-cutting design principles emerged from the TypeScript backend:

1. **Decoupling through Events**: Business logic is separated from side effects using domain events
2. **User-Centric Design**: Features like quiet hours and digest batching prioritize user experience
3. **Resilience Patterns**: Retry queues, dead-letter handling, and graceful degradation ensure system reliability
4. **Observability**: Comprehensive logging and status tracking for all major operations
5. **Versioning**: Important user content is versioned to enable history and rollback capabilities
6. **Batch Processing**: Large-scale operations are broken into manageable chunks with progress tracking

These patterns represent valuable architectural decisions that could inform future development, regardless of the implementation language or framework.
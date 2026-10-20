"""Legacy trace-event contract — DEPRECATED.

These models were used when C03 published trace events to Redis pub/sub.
That architecture has been replaced by ``app.services.xai_callback.XAITracerCallback``,
which writes granular callback events directly to MongoDB.

This file is kept as a tombstone.  Do not import from it in new code.
"""

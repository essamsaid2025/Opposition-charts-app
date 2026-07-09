"""First Team Football Analysis Platform (FAP).

Layered, plugin-driven architecture:

    UI  ->  Application Services  ->  Domain (metrics/analytics)  ->  Infrastructure

Nothing in ``fap.core`` imports Streamlit; the whole domain layer is testable
headlessly. Streamlit only appears in ``fap.ui`` and ``fap.state`` (guarded).
"""
__version__ = "1.0.0"

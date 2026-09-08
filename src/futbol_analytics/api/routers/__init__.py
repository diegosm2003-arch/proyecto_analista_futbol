"""Routers de la API, uno por area del dominio."""

from futbol_analytics.api.routers import meta, players, teams

__all__ = ["meta", "players", "teams"]

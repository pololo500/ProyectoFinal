# Navegación Inicio + Archivos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Barra Inicio · Rutinas · Archivos · Agenda, engranaje a Config, play/stop en Inicio, biblioteca (cuentos + canciones) en Archivos.

**Architecture:** Mismos destinos de Navigation. Bottom nav y drawer muestran 4 ítems. Config y Métricas se abren por toolbar / Ver detalle. Canciones salen de Config y entran a `StoriesFragment`. Última canción en SharedPreferences vía `RobotConnectionManager`.

**Tech Stack:** Android Kotlin, Material, Navigation Component, ViewBinding.

## Global Constraints

- Sin APIs nuevas en la Pi. Paleta actual. Sin FAB de celebrar. Sin Tailwind.
- Play en Inicio: última canción, o la primera; sin lista. Play disabled si no hay canciones.
- Label Archivos. No commits salvo que Teo lo pida.
- Trabajar en `main` (Teo no quiere branch nuevo).

## Archivos

Modificar menús, `MainActivity`, dashboard, stories, config, `RobotConnectionManager`, `strings.xml`.

## Tasks

1. Navegación (barra 4 + engranaje, sin overflow de Cuentos/Agenda, FAB gone).
2. Inicio: card música + Ver detalle.
3. Archivos: canciones + copy; quitar canciones de Config.
4. Prefs última canción + play/stop cableado.

Ver spec `docs/superpowers/specs/2026-08-25-app-nav-inicio-archivos-design.md`.

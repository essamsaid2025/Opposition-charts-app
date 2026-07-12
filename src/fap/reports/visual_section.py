"""Report integration: ONE section plugin renders any registered
visualization into report output - every current and future visualization is
therefore automatically report-ready with zero per-plugin code.

Usage: put {"viz_id": ..., "controls": {...}} entries in
RenderContext.meta["report_visuals"], include "visuals" in ReportSpec.section_ids."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.core.types import RenderContext
from fap.reports.builder import ReportSection, SectionOutput, section_registry


@section_registry.register
class VisualsSection(ReportSection):
    info = PluginInfo(id="visuals", name="Visualizations", category="report",
                      description="Renders any list of visualization plugins.")

    def build(self, ctx: RenderContext) -> SectionOutput:
        from fap.visuals.base import visual_registry
        from fap.visuals.renderer import Renderer
        renderer = Renderer()
        output = SectionOutput(title="Visualizations")
        for spec in ctx.meta.get("report_visuals", []):
            viz = visual_registry.create(spec["viz_id"])
            sub_ctx = RenderContext(df=ctx.df, theme=ctx.theme,
                                    controls={**ctx.controls, **spec.get("controls", {})},
                                    meta=ctx.meta)
            output.figures.append(renderer.render(viz, sub_ctx))
            output.markdown += f"\n### {viz.info.name}\n{viz.info.description}\n"
        return output

from __future__ import absolute_import, division, unicode_literals

import base64
import json
from weakref import WeakValueDictionary

import param
from param.parameterized import bothmethod

from holoviews.plotting.plotly.util import clean_internal_figure_properties

with param.logging_level('CRITICAL'):
    from plotly import utils
    import plotly.graph_objs as go

import panel as pn
from panel.pane import Viewable

from ..renderer import Renderer, MIME_TYPES, HTML_TAGS
from ...core.options import Store
from ...core import HoloMap
from .callbacks import callbacks



def _PlotlyHoloviews(fig_dict):
    """
    Custom Plotly pane constructor for use by the HoloViews Pane.
    """
    # Save plot id
    plot_id = fig_dict['_id']

    # Remove internal HoloViews properties
    clean_internal_figure_properties(fig_dict)

    # Create plotly pane
    plotly_pane = pn.pane.Plotly(fig_dict)

    # Configure pane callbacks
    plotly_pane.viewport_update_policy = 'mouseup'

    # Add pane to renderer so that we can find it again to update it
    PlotlyRenderer._plot_panes[plot_id] = plotly_pane

    # Register callbacks on pane
    for callback_cls in callbacks.values():
        plotly_pane.param.watch(
            lambda event, cls=callback_cls: cls.update_streams_from_property_update(event.new, event.obj.object),
            callback_cls.callback_property,
        )

    return plotly_pane


class PlotlyRenderer(Renderer):

    backend = param.String(default='plotly', doc="The backend name.")

    fig = param.ObjectSelector(default='auto', objects=['html', 'json', 'png', 'svg', 'auto'], doc="""
        Output render format for static figures. If None, no figure
        rendering will occur. """)

    mode_formats = {'fig': {'default': ['html', 'png', 'svg', 'json']},
                    'holomap': {'default': ['widgets', 'scrubber', 'auto']}}

    widgets = ['scrubber', 'widgets']

    _loaded = False

    _plot_panes = WeakValueDictionary()

    def __call__(self, obj, fmt='html', divuuid=None):
        plot, fmt =  self._validate(obj, fmt)
        mime_types = {'file-ext':fmt, 'mime_type': MIME_TYPES[fmt]}

        if isinstance(plot, Viewable):
            # fmt == 'html'
            return plot, mime_types
        elif fmt in ('png', 'svg'):
            return self._figure_data(plot, fmt, divuuid=divuuid), mime_types
        elif fmt == 'json':
            return self.diff(plot), mime_types


    def diff(self, plot, serialize=True):
        """
        Returns a json diff required to update an existing plot with
        the latest plot data.
        """
        diff = plot.state
        if serialize:
            return json.dumps(diff, cls=utils.PlotlyJSONEncoder)
        else:
            return diff

    @bothmethod
    def get_plot_state(self_or_cls, obj, doc=None, renderer=None, **kwargs):
        """
        Given a HoloViews Viewable return a corresponding figure dictionary.
        Allows cleaning the dictionary of any internal properties that were added
        """
        fig_dict = super(PlotlyRenderer, self_or_cls).get_plot_state(obj, renderer, **kwargs)

        # Remove internal properties (e.g. '_id', '_dim')
        clean_internal_figure_properties(fig_dict)

        # Run through Figure constructor to normalize keys
        # (e.g. to expand magic underscore notation)
        fig_dict = go.Figure(fig_dict).to_dict()

        # Remove template
        fig_dict.get('layout', {}).pop('template', None)
        return fig_dict

    def _figure_data(self, plot, fmt, as_script=False, **kwargs):
        # Wrapping plot.state in go.Figure here performs validation
        # and applies any default theme.
        figure = go.Figure(plot.state)

        if fmt in ('png', 'svg'):
            import plotly.io as pio
            data = pio.to_image(figure, fmt)

            if fmt == 'svg':
                data = data.decode('utf-8')

            if as_script:
                b64 = base64.b64encode(data).decode("utf-8")
                (mime_type, tag) = MIME_TYPES[fmt], HTML_TAGS[fmt]
                src = HTML_TAGS['base64'].format(mime_type=mime_type, b64=b64)
                div = tag.format(src=src, mime_type=mime_type, css='')
                return div
            else:
                return data
        else:
            raise ValueError("Unsupported format: {fmt}".format(fmt=fmt))


    @classmethod
    def plot_options(cls, obj, percent_size):
        factor = percent_size / 100.0
        obj = obj.last if isinstance(obj, HoloMap) else obj
        plot = Store.registry[cls.backend].get(type(obj), None)
        options = plot.lookup_options(obj, 'plot').options
        width = options.get('width', plot.width) * factor
        height = options.get('height', plot.height) * factor
        return dict(options, **{'width':int(width), 'height': int(height)})


    @classmethod
    def load_nb(cls, inline=True):
        """
        Loads the plotly notebook resources.
        """
        import panel.models.plotly # noqa
        cls._loaded = True


    @classmethod
    def trigger_plot_pane(cls, plot_id, fig_dict):
        if plot_id in cls._plot_panes:
            clean_internal_figure_properties(fig_dict)
            pane = cls._plot_panes[plot_id]
            pane.object = fig_dict


def _activate_plotly_backend(renderer):
    if renderer == "plotly":
        pn.pane.HoloViews._panes["plotly"] = _PlotlyHoloviews


Store._backend_switch_hooks.append(_activate_plotly_backend)

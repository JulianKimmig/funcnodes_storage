import {
  RendererPlugin,
  FuncNodesReactPlugin,
  RenderPluginFactoryProps,
} from "@linkdlab/funcnodes_react_flow";

const renderpluginfactory = ({
  React: _React,
  fnrf_zst: _fnrf_zst,
}: RenderPluginFactoryProps) => {
  const MyRendererPlugin: RendererPlugin = {
    handle_preview_renderers: {},
    data_overlay_renderers: {},
    data_preview_renderers: {},
    data_view_renderers: {},
    input_renderers: {},
  };

  return MyRendererPlugin;
};

const Plugin: FuncNodesReactPlugin = {
  renderpluginfactory: renderpluginfactory,
};

export default Plugin;

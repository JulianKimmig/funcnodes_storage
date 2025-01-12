// webpack.config.js
const path = require("path");
const MiniCssExtractPlugin = require("mini-css-extract-plugin");

module.exports = {
  context: __dirname,
  entry: "./src/index.tsx",

  output: {
    path: path.resolve(__dirname, "dist"),
    filename: "js/[name].js",
    library: {
      type: "module",
    },
  },
  performance: {
    maxEntrypointSize: 5 * 1024 * 1024, // 5mb
    maxAssetSize: 5 * 1024 * 1024, // 5mb
  },
  // mode: "development",
  mode: "production",
  module: {
    rules: [
      //typescript
      {
        test: /\.(tsx|ts)$/,
        use: [
          {
            loader: "ts-loader",
            options: {
              configFile: "tsconfig.json",
            },
          },
        ],
        exclude: /node_modules/,
      },
      //css
      {
        test: /\.css$/,
        use: [
          // "style-loader",
          MiniCssExtractPlugin.loader,
          { loader: "css-loader", options: { importLoaders: 5 } },
          {
            loader: "postcss-loader",
            options: {
              postcssOptions: {
                plugins: [require("autoprefixer"), require("cssnano")],
              },
            },
          },
        ],
        sideEffects: true,
      },
      //javascript
      {
        test: /\.js$/,
        use: "babel-loader",
      },
      //scss
      {
        test: /\.scss$/,
        sideEffects: true,
        use: [
          MiniCssExtractPlugin.loader,
          {
            loader: "css-loader",
            options: {
              importLoaders: 5,
              url: true, // Ensure CSS loader handles URL() paths
            },
          },

          {
            loader: "postcss-loader",
            options: {
              postcssOptions: {
                plugins: [require("autoprefixer"), require("cssnano")],
              },
            },
          },
          {
            loader: "sass-loader",
          },
        ],
      },
      //images
      {
        test: /\.(png|svg|jpg|jpeg|gif|webp)$/i,
        type: "asset/resource",
        generator: {
          filename: "img/[name][ext][query]",
        },
      },
      //fonts
      {
        test: /\.(woff|woff2|eot|ttf|otf)$/i,
        type: "asset/resource",
        generator: {
          filename: "fonts/[name][ext][query]",
        },
      },
    ],
  },

  plugins: [
    new MiniCssExtractPlugin({
      filename: "css/style.css",
      chunkFilename: "css/[name].css",
    }),
  ],
  resolve: {
    extensions: [
      ".js",
      ".jsx",
      ".tsx",
      ".ts",
      ".html",
      ".scss",
      ".css",
      ".ttf",
    ],
  },
  optimization: {
    splitChunks: false,
  },
  experiments: {
    outputModule: true,
  },
  externals: {
    react: "React",
    "react-dom": "ReactDOM",
  },
};

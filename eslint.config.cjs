"use strict";

// CommonJS rather than ESM: pre-commit installs @eslint/js and globals in its
// own environment and exposes them via NODE_PATH, which require() honours but
// import does not.
const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2018,
      // Our scripts are loaded with plain <script> tags, not as ES modules
      sourceType: "script",
      globals: {
        ...globals.browser,
        ...globals.jquery,
      },
    },
    rules: {
      strict: ["error", "global"],
      "no-unused-vars": "off",
      "init-declarations": "error",
      "no-delete-var": "error",
      "no-label-var": "error",
      "no-shadow-restricted-names": "error",
      "no-undef-init": "error",
      "no-undef": "error",
      "no-undefined": "error",
      "no-use-before-define": "error",
      "no-var": "error",
    },
  },
  {
    // This file itself runs in Node, not the browser
    files: ["eslint.config.cjs"],
    languageOptions: {
      sourceType: "commonjs",
      globals: globals.node,
    },
  },
];

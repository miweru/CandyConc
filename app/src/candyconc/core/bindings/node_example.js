const ffi = require('ffi-napi');
const path = require('path');

// Load the shared library compiled from core/bindings/search.c
const lib = ffi.Library(path.join(__dirname, 'libsearch'), {
  cc_document_search: ['int', ['string', 'string', 'char *', 'int']],
});

// Expect index path and query term as command line arguments
const [index, query] = process.argv.slice(2);
if (!index || !query) {
  console.error('usage: node node_example.js INDEX QUERY');
  process.exit(1);
}

const buf = Buffer.alloc(4096);
lib.cc_document_search(index, query, buf, buf.length);
const results = JSON.parse(buf.toString());
console.log(results);

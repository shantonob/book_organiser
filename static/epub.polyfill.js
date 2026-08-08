// Provide xmldom + JSZip as browser globals for epub.js
window.xmldom = {
  DOMParser: window.DOMParser,
  XMLSerializer: window.XMLSerializer,
  DOMImplementation: document.implementation
};

# Files for validation of CDIF metadata

This repository is for collecting JSON schema, contexts, and SHACL rule sets useful for testing CDIF metadata documents.  

Currently only have JSON schema and SHACL rules for base Discovery profile. 

CDIF-JSONLD-schema-schemaprefix.json is the same as CDIF-JSONLD-schema.json, but  schema.org is not declared as teh default in the context so all schema.org elements have a 'schema:' prefix. This was necessary to get the SHACL RULE validator working quickly....

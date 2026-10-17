// keyword search over standard text
CREATE FULLTEXT INDEX regulatory_text IF NOT EXISTS
FOR (n:Section|Requirement|Definition|Standard)
ON EACH [n.text, n.heading, n.term, n.title];

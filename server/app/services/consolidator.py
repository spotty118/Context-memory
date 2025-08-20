"""
Context consolidation service for merging and deduplicating extracted items.
"""
import hashlib
from typing import Dict, List, Any, Tuple, Optional, Set
from datetime import datetime
from difflib import SequenceMatcher
import structlog

logger = structlog.get_logger(__name__)


class ContextConsolidator:
    """Consolidates extracted context items by merging duplicates and related items."""
    
    def __init__(self):
        self.similarity_threshold = 0.8
        self.merge_threshold = 0.9
    
    def consolidate_semantic_items(
        self, 
        new_items: List[Dict[str, Any]], 
        existing_items: List[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        """
        Consolidate semantic items by merging duplicates and similar items.
        
        Returns:
            Tuple of (consolidated_items, added_ids, updated_ids)
        """
        existing_items = existing_items or []
        added_ids = []
        updated_ids = []
        
        # Create lookup for existing items
        existing_by_id = {item['id']: item for item in existing_items}
        consolidated_items = list(existing_items)
        
        for new_item in new_items:
            # Check for exact duplicates by content hash
            content_sig = self._generate_content_signature(new_item)
            
            # Find similar existing items
            similar_item, similarity = self._find_most_similar_semantic(
                new_item, existing_items
            )
            
            if similar_item and similarity >= self.merge_threshold:
                # Merge with existing item
                merged_item = self._merge_semantic_items(similar_item, new_item)
                
                # Update in consolidated list
                for i, item in enumerate(consolidated_items):
                    if item['id'] == similar_item['id']:
                        consolidated_items[i] = merged_item
                        updated_ids.append(similar_item['id'])
                        break
                
                logger.debug("semantic_item_merged", 
                           existing_id=similar_item['id'],
                           new_title=new_item['title'],
                           similarity=similarity)
            
            elif similar_item and similarity >= self.similarity_threshold:
                # Link but don't merge - add as related
                new_item['links']['references'].append(similar_item['id'])
                consolidated_items.append(new_item)
                added_ids.append(new_item['id'])
                
                logger.debug("semantic_item_linked", 
                           new_id=new_item['id'],
                           linked_to=similar_item['id'],
                           similarity=similarity)
            
            else:
                # Add as new item
                consolidated_items.append(new_item)
                added_ids.append(new_item['id'])
                
                logger.debug("semantic_item_added", 
                           new_id=new_item['id'],
                           title=new_item['title'])
        
        # Update cross-references and relationships
        consolidated_items = self._update_cross_references(consolidated_items)
        
        logger.info("semantic_consolidation_complete",
                   total_items=len(consolidated_items),
                   added=len(added_ids),
                   updated=len(updated_ids))
        
        return consolidated_items, added_ids, updated_ids
    
    def consolidate_episodic_items(
        self, 
        new_items: List[Dict[str, Any]], 
        existing_items: List[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        """
        Consolidate episodic items by deduplicating and grouping related events.
        
        Returns:
            Tuple of (consolidated_items, added_ids, updated_ids)
        """
        existing_items = existing_items or []
        added_ids = []
        updated_ids = []
        
        # Create hash lookup for exact duplicates
        existing_hashes = {item['hash']: item for item in existing_items}
        consolidated_items = list(existing_items)
        
        for new_item in new_items:
            # Check for exact duplicate by hash
            if new_item['hash'] in existing_hashes:
                # Update salience if higher
                existing_item = existing_hashes[new_item['hash']]
                if new_item['salience'] > existing_item['salience']:
                    existing_item['salience'] = new_item['salience']
                    updated_ids.append(existing_item['id'])
                
                logger.debug("episodic_item_duplicate_skipped", 
                           hash=new_item['hash'][:8])
                continue
            
            # Check for similar items (same kind, similar content)
            similar_items = self._find_similar_episodic(new_item, existing_items)
            
            if similar_items:
                # Group with similar items but keep as separate entry
                # Update neighbors for clustering
                for similar in similar_items:
                    if 'neighbors' not in similar:
                        similar['neighbors'] = []
                    if new_item['id'] not in similar['neighbors']:
                        similar['neighbors'].append(new_item['id'])
                
                new_item['neighbors'] = [item['id'] for item in similar_items]
                
                logger.debug("episodic_item_grouped", 
                           new_id=new_item['id'],
                           grouped_with=[item['id'] for item in similar_items])
            
            # Add as new item
            consolidated_items.append(new_item)
            added_ids.append(new_item['id'])
            existing_hashes[new_item['hash']] = new_item
        
        logger.info("episodic_consolidation_complete",
                   total_items=len(consolidated_items),
                   added=len(added_ids),
                   updated=len(updated_ids))
        
        return consolidated_items, added_ids, updated_ids
    
    def consolidate_artifacts(
        self, 
        new_artifacts: List[Dict[str, Any]], 
        existing_artifacts: List[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        """
        Consolidate artifacts by merging references to the same files/code.
        
        Returns:
            Tuple of (consolidated_artifacts, added_refs, updated_refs)
        """
        existing_artifacts = existing_artifacts or []
        added_refs = []
        updated_refs = []
        
        # Create lookup by ref
        existing_by_ref = {artifact['ref']: artifact for artifact in existing_artifacts}
        consolidated_artifacts = list(existing_artifacts)
        
        for new_artifact in new_artifacts:
            if new_artifact['ref'] in existing_by_ref:
                # Update existing artifact
                existing = existing_by_ref[new_artifact['ref']]
                
                # Merge neighbors
                existing_neighbors = set(existing.get('neighbors', []))
                new_neighbors = set(new_artifact.get('neighbors', []))
                merged_neighbors = list(existing_neighbors | new_neighbors)
                
                existing['neighbors'] = merged_neighbors
                updated_refs.append(new_artifact['ref'])
                
                logger.debug("artifact_updated", 
                           ref=new_artifact['ref'],
                           neighbors_count=len(merged_neighbors))
            else:
                # Add new artifact
                consolidated_artifacts.append(new_artifact)
                existing_by_ref[new_artifact['ref']] = new_artifact
                added_refs.append(new_artifact['ref'])
                
                logger.debug("artifact_added", 
                           ref=new_artifact['ref'])
        
        # Update cross-references between artifacts
        consolidated_artifacts = self._update_artifact_relationships(consolidated_artifacts)
        
        logger.info("artifact_consolidation_complete",
                   total_artifacts=len(consolidated_artifacts),
                   added=len(added_refs),
                   updated=len(updated_refs))
        
        return consolidated_artifacts, added_refs, updated_refs
    
    def _generate_content_signature(self, item: Dict[str, Any]) -> str:
        """Generate a content signature for duplicate detection."""
        content = f"{item.get('title', '')}\n{item.get('body', '')}"
        # Normalize whitespace and case
        normalized = ' '.join(content.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def _find_most_similar_semantic(
        self, 
        new_item: Dict[str, Any], 
        existing_items: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        """Find the most similar existing semantic item."""
        if not existing_items:
            return None, 0.0
        
        best_match = None
        best_similarity = 0.0
        
        new_content = f"{new_item.get('title', '')} {new_item.get('body', '')}"
        
        for existing_item in existing_items:
            # Only compare items of the same kind
            if existing_item.get('kind') != new_item.get('kind'):
                continue
            
            existing_content = f"{existing_item.get('title', '')} {existing_item.get('body', '')}"
            
            similarity = SequenceMatcher(None, new_content, existing_content).ratio()
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = existing_item
        
        return best_match, best_similarity
    
    def _find_similar_episodic(
        self, 
        new_item: Dict[str, Any], 
        existing_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Find similar episodic items for grouping."""
        similar_items = []
        
        new_snippet = new_item.get('snippet', '')
        new_kind = new_item.get('kind')
        
        for existing_item in existing_items:
            # Same kind and similar content
            if existing_item.get('kind') == new_kind:
                existing_snippet = existing_item.get('snippet', '')
                similarity = SequenceMatcher(None, new_snippet, existing_snippet).ratio()
                
                if similarity >= self.similarity_threshold:
                    similar_items.append(existing_item)
        
        return similar_items
    
    def _merge_semantic_items(
        self, 
        existing_item: Dict[str, Any], 
        new_item: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge two semantic items."""
        merged = existing_item.copy()
        
        # Merge body content
        existing_body = existing_item.get('body', '')
        new_body = new_item.get('body', '')
        
        if new_body and new_body not in existing_body:
            merged['body'] = f"{existing_body}\n\n--- Additional Context ---\n{new_body}"
        
        # Merge tags
        existing_tags = set(existing_item.get('tags', []))
        new_tags = set(new_item.get('tags', []))
        merged['tags'] = list(existing_tags | new_tags)
        
        # Merge links
        existing_refs = set(existing_item.get('links', {}).get('references', []))
        new_refs = set(new_item.get('links', {}).get('references', []))
        merged_refs = list(existing_refs | new_refs)
        
        if 'links' not in merged:
            merged['links'] = {}
        merged['links']['references'] = merged_refs
        
        # Update salience (take higher value)
        merged['salience'] = max(
            existing_item.get('salience', 0.5),
            new_item.get('salience', 0.5)
        )
        
        # Update status if new item has higher priority status
        status_priority = {'rejected': 0, 'provisional': 1, 'accepted': 2}
        existing_priority = status_priority.get(existing_item.get('status', 'provisional'), 1)
        new_priority = status_priority.get(new_item.get('status', 'provisional'), 1)
        
        if new_priority > existing_priority:
            merged['status'] = new_item.get('status', 'provisional')
        
        # Update timestamps
        merged['updated_at'] = datetime.utcnow().isoformat()
        
        return merged
    
    def _update_cross_references(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Update cross-references between items."""
        item_ids = {item['id'] for item in items}
        
        for item in items:
            # Validate and clean references
            if 'links' in item and 'references' in item['links']:
                valid_refs = [
                    ref for ref in item['links']['references'] 
                    if ref in item_ids
                ]
                item['links']['references'] = valid_refs
        
        return items
    
    def _update_artifact_relationships(self, artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Update relationships between artifacts based on file paths."""
        # Group artifacts by file/directory
        by_file = {}
        for artifact in artifacts:
            ref = artifact['ref']
            if ref.startswith('CODE:'):
                file_path = ref[5:].split('#')[0]  # Remove line numbers
                if file_path not in by_file:
                    by_file[file_path] = []
                by_file[file_path].append(artifact)
        
        # Update neighbors for artifacts in the same file
        for file_path, file_artifacts in by_file.items():
            if len(file_artifacts) > 1:
                artifact_refs = [a['ref'] for a in file_artifacts]
                for artifact in file_artifacts:
                    neighbors = [ref for ref in artifact_refs if ref != artifact['ref']]
                    existing_neighbors = set(artifact.get('neighbors', []))
                    artifact['neighbors'] = list(existing_neighbors | set(neighbors))
        
        return artifacts


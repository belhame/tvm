from rest_framework import serializers

from .catalogue_models import CatalogueImport, CatalogueProduct, CatalogueWarranty
from .catalogue_service import usable_code


class CatalogueImportSerializer(serializers.ModelSerializer):
    imported_by_name = serializers.SerializerMethodField()
    class Meta:
        model = CatalogueImport
        fields = ['id', 'filename', 'sha256', 'imported_at', 'imported_by', 'imported_by_name', 'product_count', 'warranty_count', 'is_active', 'metadata']
    def get_imported_by_name(self, obj):
        return (obj.imported_by.get_full_name() or obj.imported_by.username) if obj.imported_by else 'Compte supprimé'


class CatalogueProductSerializer(serializers.ModelSerializer):
    import_id = serializers.IntegerField(source='snapshot_id', read_only=True)
    code_is_usable = serializers.SerializerMethodField()
    code_is_ambiguous = serializers.SerializerMethodField()
    equipment_model_suggestion = serializers.SerializerMethodField()
    class Meta:
        model = CatalogueProduct
        fields = ['id', 'import_id', 'range_name', 'product_name', 'product_code', 'structure', 'launch_year', 'manufacturing_part_number', 'catalogue_number', 'market_status', 'replacement_product', 'replacement_part_number', 'version', 'return_text', 'source_sheet', 'source_row', 'raw_data', 'code_is_usable', 'code_is_ambiguous', 'equipment_model_suggestion']
    def get_code_is_usable(self, obj):
        return usable_code(obj.product_code)
    def get_code_is_ambiguous(self, obj):
        if not usable_code(obj.product_code):
            return False
        key = (obj.structure.strip().casefold(), obj.product_code.strip().casefold())
        return self.context.get('collision_counts', {}).get(key, 0) > 1
    def get_equipment_model_suggestion(self, obj):
        return obj.product_name if obj.product_name and len(obj.product_name) <= 120 else None


class CatalogueWarrantySerializer(serializers.ModelSerializer):
    import_id = serializers.IntegerField(source='snapshot_id', read_only=True)
    class Meta:
        model = CatalogueWarranty
        fields = ['id', 'import_id', 'scope', 'category', 'product_name', 'brand_group', 'duration_text', 'duration_months', 'conditions', 'source_sheet', 'source_row', 'source_column', 'raw_data']

from typing import TYPE_CHECKING, Any, TypeVar, overload

from pydantic import BaseModel, Field

from backend.common.response.response_code import CustomResponse, CustomResponseCode
from backend.utils.serializers import MsgSpecJSONResponse

if TYPE_CHECKING:
    from fastapi import Response

SchemaT = TypeVar("SchemaT")


class ResponseModel(BaseModel):
    """
    Generic unified return model without return data schema

    Example::

        @router.get('/test', response_model=ResponseModel)
        def test():
            return ResponseModel(data={'test': 'test'})


        @router.get('/test')
        def test() -> ResponseModel:
            return ResponseModel(data={'test': 'test'})


        @router.get('/test')
        def test() -> ResponseModel:
            res = CustomResponseCode.HTTP_200
            return ResponseModel(code=res.code, msg=res.msg, data={'test': 'test'})
    """

    code: int = Field(
        CustomResponseCode.HTTP_200.code, description="Return status code"
    )
    msg: str = Field(CustomResponseCode.HTTP_200.msg, description="Return information")
    data: Any | None = Field(None, description="Returned data")


class ResponseSchemaModel[SchemaT](ResponseModel):
    """
    Generic unified return model with return data schema

    Example::

        @router.get('/test', response_model=ResponseSchemaModel[GetApiDetail])
        def test():
            return ResponseSchemaModel[GetApiDetail](data=GetApiDetail(...))


        @router.get('/test')
        def test() -> ResponseSchemaModel[GetApiDetail]:
            return ResponseSchemaModel[GetApiDetail](data=GetApiDetail(...))


        @router.get('/test')
        def test() -> ResponseSchemaModel[GetApiDetail]:
            res = CustomResponseCode.HTTP_200
            return ResponseSchemaModel[GetApiDetail](code=res.code, msg=res.msg, data=GetApiDetail(...))
    """

    data: SchemaT


class ResponseBase:
    """General return method"""

    @staticmethod
    def __response(
        *,
        res: CustomResponseCode | CustomResponse,
        data: Any | None,
    ) -> ResponseModel | ResponseSchemaModel:
        """
        General return method

        :param res: Return information
        :param data: Return data
        :return:
        """
        if data is None:
            return ResponseModel(code=res.code, msg=res.msg, data=data)
        return ResponseSchemaModel[Any](code=res.code, msg=res.msg, data=data)

    @overload
    def success(
        self,
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_200,
        data: None = None,
    ) -> ResponseModel: ...

    @overload
    def success(
        self,
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_200,
        data: SchemaT,
    ) -> ResponseSchemaModel[SchemaT]: ...

    def success(
        self,
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_200,
        data: Any | None = None,
    ) -> ResponseModel | ResponseSchemaModel:
        """
        Successful response

        :param res: Return information
        :param data: Return data
        :return:
        """
        return self.__response(res=res, data=data)

    @overload
    def fail(
        self,
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_400,
        data: None = None,
    ) -> ResponseModel: ...

    @overload
    def fail(
        self,
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_400,
        data: SchemaT,
    ) -> ResponseSchemaModel[SchemaT]: ...

    def fail(
        self,
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_400,
        data: Any = None,
    ) -> ResponseModel | ResponseSchemaModel:
        """
        Failed response

        :param res: Return information
        :param data: Return data
        :return:
        """
        return self.__response(res=res, data=data)

    @staticmethod
    def fast_success(
        *,
        res: CustomResponseCode | CustomResponse = CustomResponseCode.HTTP_200,
        data: Any | None = None,
    ) -> Response:
        """
        Improve the response speed of the interface,
        with significant performance improvement when parsing large json,
        but will lose pydantic parsing and validation

        .. warning::

            When using this return method, you cannot specify the interface parameter
            response_model and arrow return type

        :param res: Return information
        :param data: Return data
        :return:
        """
        return MsgSpecJSONResponse({"code": res.code, "msg": res.msg, "data": data})


response_base: ResponseBase = ResponseBase()
